"""Unit tests for openviper.auth.token_auth module."""

from __future__ import annotations

import asyncio
import datetime
import secrets
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth import authentications as token_auth
from openviper.auth.authentications import (
    TokenAuthentication,
    clear_api_key_cache,
    clear_token_auth_cache,
    create_api_key_credential,
    create_api_key_pair,
    create_token,
    evict_api_key_cache_if_full,
    evict_token_cache_if_full,
    get_api_key_cache_lock,
    get_token_cache_lock,
    hash_token,
    reverse_api_key_credential,
    revoke_api_key_pair,
    revoke_token,
)

# Patch target shortcuts - keeps individual test lines within the 100-char limit.
ensure_auth_tokens_table = "openviper.auth.authentications.ensure_auth_tokens_table"
get_engine = "openviper.auth.authentications.get_engine"
get_user_cached = "openviper.auth.authentications.get_user_cached"
get_user_by_id = "openviper.auth.authentications.get_user_by_id"


class FakeRequest:
    """Minimal request stub for authentication tests."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.path = "/"
        self.method = "GET"


class TestHashToken:
    def test_deterministic(self) -> None:
        assert hash_token("abc") == hash_token("abc")

    def test_differs_for_different_inputs(self) -> None:
        assert hash_token("abc") != hash_token("xyz")

    def test_returns_64_char_hex(self) -> None:
        result = hash_token("test-token")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestGetTokenCacheLock:
    def test_creates_lock_on_first_call(self) -> None:
        original = token_auth._TOKEN_CACHE_LOCK_REF[0]
        token_auth._TOKEN_CACHE_LOCK_REF[0] = None
        try:
            lock = get_token_cache_lock()
            assert isinstance(lock, asyncio.Lock)
        finally:
            token_auth._TOKEN_CACHE_LOCK_REF[0] = original

    def test_returns_same_lock_on_repeat_calls(self) -> None:
        lock1 = get_token_cache_lock()
        lock2 = get_token_cache_lock()
        assert lock1 is lock2


class TestEvictIfFull:
    def setup_method(self) -> None:
        clear_token_auth_cache()

    def test_no_eviction_below_capacity(self) -> None:
        token_auth.TOKEN_CACHE["k1"] = (1, time.monotonic() + 100)
        token_auth.TOKEN_CACHE["k2"] = (2, time.monotonic() + 100)
        evict_token_cache_if_full(time.monotonic())
        assert len(token_auth.TOKEN_CACHE) == 2

    def test_evicts_expired_entries_when_over_capacity(self) -> None:
        now = time.monotonic()
        for i in range(5):
            token_auth.TOKEN_CACHE[f"stale_{i}"] = (i, now - 10)

        with patch.object(token_auth, "TOKEN_CACHE_MAXSIZE", 3):
            evict_token_cache_if_full(now)

        assert len(token_auth.TOKEN_CACHE) < 5


class TestClearTokenAuthCache:
    def test_clears_cache(self) -> None:
        token_auth.TOKEN_CACHE["some_hash"] = (99, time.monotonic() + 600)
        clear_token_auth_cache()
        assert len(token_auth.TOKEN_CACHE) == 0


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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                raw, record = await create_token(user_id=42)

        assert isinstance(raw, str)
        assert len(raw) == 40  # secrets.token_hex(20) → 40 hex chars
        assert record["user_id"] == 42
        assert record["is_active"] is True

    def test_raw_token_is_40_chars_and_unique(self) -> None:
        r1 = secrets.token_hex(20)
        r2 = secrets.token_hex(20)
        assert len(r1) == 40
        assert len(r2) == 40
        assert r1 != r2


class TestRevokeToken:
    def setup_method(self) -> None:
        clear_token_auth_cache()

    @pytest.mark.asyncio
    async def test_updates_db_and_evicts_cache(self) -> None:
        raw = "a" * 40
        key_hash = hash_token(raw)
        token_auth.TOKEN_CACHE[key_hash] = (7, time.monotonic() + 600)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                await revoke_token(raw)

        assert key_hash not in token_auth.TOKEN_CACHE
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                await revoke_token(raw)  # should not raise


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
        key_hash = hash_token(raw)
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    get_user_by_id,
                    new=AsyncMock(return_value=fake_user),
                ):
                    auth = TokenAuthentication()
                    result = await auth.authenticate(request)

        assert result is not None
        user, info = result
        assert user is fake_user
        assert info["type"] == "token"
        assert "token" not in info
        assert key_hash not in token_auth.TOKEN_CACHE

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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_authenticate_expired_token_returns_none(self) -> None:
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    get_user_cached,
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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                auth = TokenAuthentication()
                result = await auth.authenticate(request)

        assert result is None

    async def test_token_authenticate_falls_back_to_db(self) -> None:
        raw = "j" * 40
        key_hash = hash_token(raw)
        request = FakeRequest(headers={"authorization": f"Token {raw}"})

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

        with patch(ensure_auth_tokens_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                with patch(
                    get_user_by_id,
                    new=AsyncMock(return_value=fake_user),
                ):
                    auth = TokenAuthentication()
                    result = await auth.authenticate(request)

        assert result is not None
        assert key_hash not in token_auth.TOKEN_CACHE


def test_authenticate_header_returns_token() -> None:
    request = FakeRequest()
    auth = TokenAuthentication()
    assert auth.authenticate_header(request) == "Token"


ensure_api_keys_table = "openviper.auth.authentications.ensure_api_keys_table"
get_engine = "openviper.auth.authentications.get_engine"


class TestApiKeyPair:
    """Tests for the API key pair lifecycle functions."""

    def setup_method(self) -> None:
        clear_api_key_cache()

    @pytest.mark.asyncio
    async def test_create_api_key_credential_joins_key_and_secret(self) -> None:
        """Storing a credential hashes ``key.secret`` and persists the row."""
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.credential_hash = "hash_placeholder"
        mock_row.user_id = 10
        mock_row.name = "test-key"
        mock_row.scopes = "read"
        mock_row.is_active = True
        mock_row.created_at = None
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(ensure_api_keys_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                record = await create_api_key_credential(
                    "mykey", "mysecret", 10, name="test-key", scopes="read"
                )

        assert record["user_id"] == 10
        assert record["name"] == "test-key"
        assert record["scopes"] == "read"
        assert record["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_api_key_pair_can_store_primary_order_only(self) -> None:
        """When ``store_reverse=False``, only the forward credential is stored."""
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.credential_hash = "hash_placeholder"
        mock_row.user_id = 5
        mock_row.name = None
        mock_row.scopes = ""
        mock_row.is_active = True
        mock_row.created_at = None
        mock_row.expires_at = None

        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=mock_row)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(ensure_api_keys_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                raw, record = await create_api_key_pair(5, store_reverse=False)

        assert isinstance(raw, str)
        parts = raw.split(".")
        assert len(parts) == 2
        assert len(parts[0]) == 64  # 32 bytes -> 64 hex chars
        assert len(parts[1]) == 64
        assert record["user_id"] == 5

    @pytest.mark.asyncio
    async def test_create_api_key_pair_stores_both_credential_orders(self) -> None:
        """By default both ``key.secret`` and ``secret.key`` are stored."""
        call_count = 0

        async def mock_execute(stmt: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_row = MagicMock()
            mock_row.id = call_count
            mock_row.credential_hash = f"hash_{call_count}"
            mock_row.user_id = 7
            mock_row.name = "both"
            mock_row.scopes = "read write"
            mock_row.is_active = True
            mock_row.created_at = None
            mock_row.expires_at = None
            result = MagicMock()
            result.one = MagicMock(return_value=mock_row)
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = mock_execute

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch(ensure_api_keys_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                raw, record = await create_api_key_pair(7, name="both", scopes="read write")

        assert call_count == 2  # forward + reverse
        assert record["user_id"] == 7

    @pytest.mark.asyncio
    async def test_reverse_api_key_credential_rejects_invalid_values(self) -> None:
        """``reverse_api_key_credential`` raises ``ValueError`` on empty inputs."""
        with pytest.raises(ValueError, match="non-empty"):
            await reverse_api_key_credential("", "secret")

        with pytest.raises(ValueError, match="non-empty"):
            await reverse_api_key_credential("key", "")

    @pytest.mark.asyncio
    async def test_reverse_api_key_credential_reverses_valid_pair(self) -> None:
        """Reversing ``key.secret`` produces the hash of ``secret.key``."""
        result = await reverse_api_key_credential("mykey", "mysecret")
        expected = hash_token("mysecret.mykey")
        assert result == expected

    @pytest.mark.asyncio
    async def test_revoke_api_key_pair_revokes_both_orders(self) -> None:
        """Revoking a pair marks both credential orders inactive in the DB."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        # Pre-populate cache so we can verify eviction
        forward_hash = hash_token("akey.asecret")
        reverse_hash = hash_token("asecret.akey")
        token_auth.API_KEY_CACHE[forward_hash] = (1, "read", time.monotonic() + 600)
        token_auth.API_KEY_CACHE[reverse_hash] = (1, "read", time.monotonic() + 600)

        with patch(ensure_api_keys_table, new=AsyncMock()):
            with patch(get_engine, new=AsyncMock(return_value=mock_engine)):
                await revoke_api_key_pair("akey", "asecret")

        mock_conn.execute.assert_called_once()
        assert forward_hash not in token_auth.API_KEY_CACHE
        assert reverse_hash not in token_auth.API_KEY_CACHE
