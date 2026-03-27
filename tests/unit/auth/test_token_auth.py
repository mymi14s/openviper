"""Unit tests for openviper.auth.token_auth module."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth import authentications as token_auth
from openviper.auth.authentications import (
    TokenAuthentication,
    _evict_if_full,
    _get_token_cache_lock,
    _hash_token,
    clear_token_auth_cache,
    create_token,
    revoke_token,
)

# Patch target shortcuts — keeps individual test lines within the 100-char limit.
_P_ENSURE = "openviper.auth.authentications._ensure_table"
_P_ENGINE = "openviper.auth.authentications.get_engine"
_P_USER = "openviper.auth.authentications.get_user_cached"


class FakeRequest:
    """Minimal request stub for authentication tests."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.path = "/"
        self.method = "GET"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestHashToken:
    def test_deterministic(self) -> None:
        assert _hash_token("abc") == _hash_token("abc")

    def test_differs_for_different_inputs(self) -> None:
        assert _hash_token("abc") != _hash_token("xyz")

    def test_returns_64_char_hex(self) -> None:
        result = _hash_token("test-token")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestGetTokenCacheLock:
    def test_creates_lock_on_first_call(self) -> None:
        original = token_auth._TOKEN_CACHE_LOCK
        token_auth._TOKEN_CACHE_LOCK = None
        try:
            lock = _get_token_cache_lock()
            assert isinstance(lock, asyncio.Lock)
        finally:
            token_auth._TOKEN_CACHE_LOCK = original

    def test_returns_same_lock_on_repeat_calls(self) -> None:
        lock1 = _get_token_cache_lock()
        lock2 = _get_token_cache_lock()
        assert lock1 is lock2


class TestEvictIfFull:
    def setup_method(self) -> None:
        clear_token_auth_cache()

    def test_no_eviction_below_capacity(self) -> None:
        token_auth._TOKEN_CACHE["k1"] = (1, time.monotonic() + 100)
        token_auth._TOKEN_CACHE["k2"] = (2, time.monotonic() + 100)
        _evict_if_full(time.monotonic())
        assert len(token_auth._TOKEN_CACHE) == 2

    def test_evicts_expired_entries_when_over_capacity(self) -> None:
        now = time.monotonic()
        for i in range(5):
            token_auth._TOKEN_CACHE[f"stale_{i}"] = (i, now - 10)

        with patch.object(token_auth, "_TOKEN_CACHE_MAXSIZE", 3):
            _evict_if_full(now)

        assert len(token_auth._TOKEN_CACHE) < 5


class TestClearTokenAuthCache:
    def test_clears_cache(self) -> None:
        token_auth._TOKEN_CACHE["some_hash"] = (99, time.monotonic() + 600)
        clear_token_auth_cache()
        assert len(token_auth._TOKEN_CACHE) == 0


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------


class TestCreateToken:
    @pytest.mark.asyncio
    async def test_returns_raw_token_and_record(self) -> None:
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.key_hash = "abc" * 21  # 63 chars (placeholder)
        mock_row.user_id = 42
        mock_row.created_at = None
        mock_row.expires_at = None
        mock_row.is_active = True

        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                raw, record = await create_token(user_id=42)

        assert isinstance(raw, str)
        assert len(raw) == 40  # secrets.token_hex(20) → 40 hex chars
        assert record["user_id"] == 42
        assert record["is_active"] is True

    def test_raw_token_is_40_chars_and_unique(self) -> None:
        import secrets

        r1 = secrets.token_hex(20)
        r2 = secrets.token_hex(20)
        assert len(r1) == 40
        assert len(r2) == 40
        assert r1 != r2


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------


class TestRevokeToken:
    def setup_method(self) -> None:
        clear_token_auth_cache()

    @pytest.mark.asyncio
    async def test_updates_db_and_evicts_cache(self) -> None:
        raw = "a" * 40
        key_hash = _hash_token(raw)
        token_auth._TOKEN_CACHE[key_hash] = (7, time.monotonic() + 600)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                await revoke_token(raw)

        assert key_hash not in token_auth._TOKEN_CACHE
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_missing_token_does_not_raise(self) -> None:
        raw = "b" * 40

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                await revoke_token(raw)  # should not raise


# ---------------------------------------------------------------------------
# TokenAuthentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTokenAuthentication:
    def setup_method(self) -> None:
        clear_token_auth_cache()

    async def test_authenticate_no_header(self) -> None:
        request = FakeRequest()
        auth = TokenAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_wrong_scheme(self) -> None:
        request = FakeRequest(headers={"authorization": "Bearer some-jwt"})
        auth = TokenAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_empty_token_after_prefix(self) -> None:
        request = FakeRequest(headers={"authorization": "Token "})
        auth = TokenAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_success_via_db(self) -> None:
        raw = "c" * 40
        key_hash = _hash_token(raw)
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        fake_user = MagicMock()
        fake_user.is_active = True

        mock_row = MagicMock()
        mock_row.user_id = 5
        mock_row.is_active = True
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    _P_USER,
                    new=AsyncMock(return_value=fake_user),
                ):
                    auth = TokenAuthentication()
                    result = await auth.authenticate(request)

        assert result is not None
        user, info = result
        assert user is fake_user
        assert info["type"] == "token"
        assert info["token"] == raw
        # Cache should be populated after successful DB lookup
        assert key_hash in token_auth._TOKEN_CACHE

    async def test_authenticate_success_via_cache(self) -> None:
        raw = "d" * 40
        key_hash = _hash_token(raw)
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        fake_user = MagicMock()
        fake_user.is_active = True

        # Pre-populate cache
        token_auth._TOKEN_CACHE[key_hash] = (9, time.monotonic() + 600)

        with patch(
            _P_USER,
            new=AsyncMock(return_value=fake_user),
        ):
            auth = TokenAuthentication()
            result = await auth.authenticate(request)

        assert result is not None
        user, info = result
        assert user is fake_user
        assert info["type"] == "token"

    async def test_authenticate_inactive_token_returns_none(self) -> None:
        raw = "e" * 40
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        mock_row = MagicMock()
        mock_row.user_id = 5
        mock_row.is_active = False
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_authenticate_token_not_found_in_db(self) -> None:
        raw = "f" * 40
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_authenticate_expired_token_returns_none(self) -> None:
        import datetime

        raw = "g" * 40
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        past = datetime.datetime(2000, 1, 1)

        mock_row = MagicMock()
        mock_row.user_id = 3
        mock_row.is_active = True
        mock_row.expires_at = past

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_authenticate_inactive_user_returns_none(self) -> None:
        raw = "h" * 40
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        fake_user = MagicMock()
        fake_user.is_active = False

        mock_row = MagicMock()
        mock_row.user_id = 10
        mock_row.is_active = True
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    _P_USER,
                    new=AsyncMock(return_value=fake_user),
                ):
                    auth = TokenAuthentication()
                    result = await auth.authenticate(request)

        assert result is None

    async def test_authenticate_db_error_returns_none(self) -> None:
        raw = "i" * 40
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(side_effect=RuntimeError("DB down"))

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_cache_evicts_stale_entry_on_hit(self) -> None:
        raw = "j" * 40
        key_hash = _hash_token(raw)
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

        # Plant an expired cache entry
        token_auth._TOKEN_CACHE[key_hash] = (55, time.monotonic() - 1)

        mock_row = MagicMock()
        mock_row.user_id = 55
        mock_row.is_active = True
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_ctx)

        fake_user = MagicMock()
        fake_user.is_active = True

        with patch(_P_ENSURE, new=AsyncMock()):
            with patch(_P_ENGINE, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    _P_USER,
                    new=AsyncMock(return_value=fake_user),
                ):
                    auth = TokenAuthentication()
                    result = await auth.authenticate(request)

        # Should fall through to DB and succeed
        assert result is not None
        # Cache should now hold the refreshed entry
        assert key_hash in token_auth._TOKEN_CACHE


def test_authenticate_header_returns_token() -> None:
    request = FakeRequest()
    auth = TokenAuthentication()
    assert auth.authenticate_header(request) == "Token"
