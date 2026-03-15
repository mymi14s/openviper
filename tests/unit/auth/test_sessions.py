"""Unit tests for openviper.auth.sessions module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth import sessions
from openviper.auth.sessions import (
    _get_session_cache_lock,
    _is_valid_session_key,
    clear_session_cache,
    create_session,
    delete_session,
    generate_session_key,
    get_user_from_session,
)


class TestGenerateSessionKey:
    """Tests for generate_session_key function."""

    def test_generates_url_safe_key(self):

        key = generate_session_key()

        # URL-safe base64 should only contain alphanumeric, -, _
        assert all(c.isalnum() or c in ("-", "_") for c in key)

    def test_generates_unique_keys(self):

        keys = {generate_session_key() for _ in range(100)}
        assert len(keys) == 100  # All keys should be unique

    def test_generates_key_with_sufficient_entropy(self):

        key = generate_session_key()
        # token_urlsafe(48) produces ~64 character string
        assert len(key) >= 60


class TestIsValidSessionKey:
    """Tests for _is_valid_session_key function."""

    def test_valid_key_returns_true(self):

        # Must be at least 32 chars (security requirement)
        assert _is_valid_session_key("abc123XYZ_-abcdefghijk1234567890") is True

    def test_empty_string_returns_false(self):

        assert _is_valid_session_key("") is False

    def test_none_returns_false(self):

        assert _is_valid_session_key(None) is False

    def test_too_short_returns_false(self):

        assert _is_valid_session_key("abc123XYZ_-") is False  # Less than 32 chars

    def test_too_long_returns_false(self):

        assert _is_valid_session_key("a" * 200) is False  # Over 128 chars

    def test_invalid_characters_return_false(self):

        assert _is_valid_session_key("abc<script>") is False
        assert _is_valid_session_key("abc def") is False
        assert _is_valid_session_key("abc\n123") is False


class TestCreateSession:
    """Tests for create_session function."""

    @pytest.mark.asyncio
    async def test_creates_session_with_user_id(self):

        with patch("openviper.auth.sessions._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.sessions.get_engine") as mock_engine:
                # Mock the async context manager chain
                mock_conn = MagicMock()
                mock_conn.execute = AsyncMock()
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_context))

                session_key = await create_session(user_id=42)

        assert session_key is not None
        assert len(session_key) > 0

    @pytest.mark.asyncio
    async def test_creates_session_with_extra_data(self):

        with patch("openviper.auth.sessions._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.sessions.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_conn.execute = AsyncMock()
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_context))

                session_key = await create_session(user_id=42, data={"role": "admin"})

        assert session_key is not None


class TestGetUserFromSession:
    """Tests for get_user_from_session function."""

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_cookie(self):

        with patch("openviper.auth.sessions.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            result = await get_user_from_session("other_cookie=value")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_session_key(self):

        with patch("openviper.auth.sessions.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            # Invalid session key with special characters
            result = await get_user_from_session("sessionid=<script>alert</script>")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_from_cache(self):

        mock_user = MagicMock()
        mock_user.pk = 42

        # Prime the cache - key must be at least 32 chars

        valid_key = "valid_session_key_1234567890abcde"  # 34 chars

        sessions._SESSION_CACHE[valid_key] = (mock_user, time.monotonic() + 100)

        with patch("openviper.auth.sessions.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            result = await get_user_from_session(f"sessionid={valid_key}")

        assert result is mock_user

        # Cleanup
        sessions._SESSION_CACHE.clear()

    @pytest.mark.asyncio
    async def test_returns_none_for_expired_session(self):

        with patch("openviper.auth.sessions.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"

            with patch("openviper.auth.sessions._ensure_table", new=AsyncMock()):
                with patch("openviper.auth.sessions.get_engine") as mock_engine:
                    mock_conn = MagicMock()
                    mock_result = MagicMock()
                    mock_result.fetchone.return_value = None  # No session found
                    mock_conn.execute = AsyncMock(return_value=mock_result)
                    mock_context = MagicMock()
                    mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_context.__aexit__ = AsyncMock(return_value=None)
                    mock_engine.return_value = MagicMock(
                        connect=MagicMock(return_value=mock_context)
                    )

                    result = await get_user_from_session("sessionid=valid_key_1234567890abcdefgh")

        assert result is None


class TestDeleteSession:
    """Tests for delete_session function."""

    @pytest.mark.asyncio
    async def test_deletes_session_from_database(self):

        with patch("openviper.auth.sessions._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.sessions.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_conn.execute = AsyncMock()
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_context))

                await delete_session("test-session-key")

        # Should have been called (delete session + delete expired)
        assert mock_conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_invalidates_cache(self):
        # Prime the cache

        sessions._SESSION_CACHE["session-to-delete"] = (MagicMock(), time.monotonic() + 100)

        with patch("openviper.auth.sessions._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.sessions.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_conn.execute = AsyncMock()
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_context))

                await delete_session("session-to-delete")

        assert "session-to-delete" not in sessions._SESSION_CACHE


class TestClearSessionCache:
    """Tests for clear_session_cache function."""

    def test_clears_cache(self):

        sessions._SESSION_CACHE["key1"] = (MagicMock(), time.monotonic() + 100)
        sessions._SESSION_CACHE["key2"] = (MagicMock(), time.monotonic() + 100)

        clear_session_cache()

        assert len(sessions._SESSION_CACHE) == 0


class TestGetSessionCacheLock:
    """Tests for _get_session_cache_lock function."""

    def test_creates_lock_if_none(self):

        original = sessions._SESSION_CACHE_LOCK
        sessions._SESSION_CACHE_LOCK = None

        try:
            lock = _get_session_cache_lock()
            assert lock is not None

            assert isinstance(lock, asyncio.Lock)
        finally:
            sessions._SESSION_CACHE_LOCK = original

    def test_returns_existing_lock(self):

        lock1 = _get_session_cache_lock()
        lock2 = _get_session_cache_lock()

        assert lock1 is lock2
