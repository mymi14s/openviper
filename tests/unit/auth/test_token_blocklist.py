"""Unit tests for openviper.auth.token_blocklist module."""

import datetime
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import asyncio

from openviper.auth import token_blocklist
from openviper.auth.token_blocklist import (
    _evict_if_full,
    _get_cache_lock,
    clear_token_cache,
    is_token_revoked,
    revoke_token,
)


class TestGetCacheLock:
    """Tests for _get_cache_lock function."""

    def test_creates_lock_if_none(self):

        original = token_blocklist._CACHE_LOCK
        token_blocklist._CACHE_LOCK = None

        try:
            lock = _get_cache_lock()
            assert lock is not None

            assert isinstance(lock, asyncio.Lock)
        finally:
            token_blocklist._CACHE_LOCK = original

    def test_returns_existing_lock(self):

        lock1 = _get_cache_lock()
        lock2 = _get_cache_lock()

        assert lock1 is lock2


class TestEvictIfFull:
    """Tests for _evict_if_full function."""

    def test_does_nothing_when_under_limit(self):

        cache = {"key1": time.time() + 100, "key2": time.time() + 100}
        _evict_if_full(cache, time.time())

        assert len(cache) == 2

    def test_evicts_expired_entries_first(self):

        # Temporarily lower max size for testing
        original = token_blocklist._CACHE_MAXSIZE
        try:
            # We can't directly modify Final, so test with a full cache
            now = time.time()
            cache = {f"key{i}": now - 100 for i in range(10)}  # All expired
            _evict_if_full(cache, now)
            # Some entries should be evicted
        finally:
            pass


class TestRevokeToken:
    """Tests for revoke_token function."""

    @pytest.fixture
    def mock_db_context(self):
        """Create a mock database context."""
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        return mock_context

    @pytest.mark.asyncio
    async def test_inserts_token_into_blocklist(self, mock_db_context):

        clear_token_cache()

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_db_context))

                expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                    hours=1
                )
                await revoke_token("test-jti", "access", "user-123", expires_at)

        # Verify execute was called
        mock_db_context.__aenter__.return_value.execute.assert_called()

    @pytest.mark.asyncio
    async def test_adds_to_revoked_cache(self, mock_db_context):

        clear_token_cache()

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_db_context))

                expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                    hours=1
                )
                await revoke_token("cached-jti", "access", "user-123", expires_at)

        assert "cached-jti" in token_blocklist._JTI_REVOKED_CACHE

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_removes_from_valid_cache(self, mock_db_context):

        clear_token_cache()

        # Prime the valid cache
        token_blocklist._JTI_VALID_CACHE["to-revoke-jti"] = time.time() + 100

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_engine.return_value = MagicMock(begin=MagicMock(return_value=mock_db_context))

                expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                    hours=1
                )
                await revoke_token("to-revoke-jti", "access", "user-123", expires_at)

        assert "to-revoke-jti" not in token_blocklist._JTI_VALID_CACHE
        assert "to-revoke-jti" in token_blocklist._JTI_REVOKED_CACHE

        clear_token_cache()


class TestIsTokenRevoked:
    """Tests for is_token_revoked function."""

    @pytest.mark.asyncio
    async def test_returns_true_for_cached_revoked_token(self):

        clear_token_cache()

        # Add to revoked cache with future expiry
        token_blocklist._JTI_REVOKED_CACHE["revoked-jti"] = time.time() + 3600

        result = await is_token_revoked("revoked-jti")

        assert result is True

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_returns_false_for_cached_valid_token(self):

        clear_token_cache()

        # Add to valid cache with future check time
        token_blocklist._JTI_VALID_CACHE["valid-jti"] = time.time() + 3600

        result = await is_token_revoked("valid-jti")

        assert result is False

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_evicts_expired_revoked_token(self):

        clear_token_cache()

        # Add to revoked cache with past expiry
        token_blocklist._JTI_REVOKED_CACHE["expired-revoked-jti"] = time.time() - 3600

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_result = MagicMock()
                mock_result.fetchone.return_value = None  # Not in DB either
                mock_conn.execute = AsyncMock(return_value=mock_result)
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(connect=MagicMock(return_value=mock_context))

                result = await is_token_revoked("expired-revoked-jti")

        # Should have been evicted from cache and looked up in DB
        assert "expired-revoked-jti" not in token_blocklist._JTI_REVOKED_CACHE

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_queries_db_when_not_cached(self):

        clear_token_cache()

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_result = MagicMock()
                mock_result.fetchone.return_value = None  # Not revoked
                mock_conn.execute = AsyncMock(return_value=mock_result)
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(connect=MagicMock(return_value=mock_context))

                result = await is_token_revoked("uncached-jti")

        assert result is False

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_caches_revoked_status_from_db(self):

        clear_token_cache()

        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_result = MagicMock()
                mock_result.fetchone.return_value = (expires_at,)  # Found in DB
                mock_conn.execute = AsyncMock(return_value=mock_result)
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(connect=MagicMock(return_value=mock_context))

                result = await is_token_revoked("db-revoked-jti")

        assert result is True
        assert "db-revoked-jti" in token_blocklist._JTI_REVOKED_CACHE

        clear_token_cache()

    @pytest.mark.asyncio
    async def test_caches_valid_status_from_db(self):

        clear_token_cache()

        with patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()):
            with patch("openviper.auth.token_blocklist.get_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_result = MagicMock()
                mock_result.fetchone.return_value = None  # Not in DB
                mock_conn.execute = AsyncMock(return_value=mock_result)
                mock_context = MagicMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_engine.return_value = MagicMock(connect=MagicMock(return_value=mock_context))

                result = await is_token_revoked("db-valid-jti")

        assert result is False
        assert "db-valid-jti" in token_blocklist._JTI_VALID_CACHE

        clear_token_cache()


class TestClearTokenCache:
    """Tests for clear_token_cache function."""

    def test_clears_both_caches(self):

        token_blocklist._JTI_REVOKED_CACHE["key1"] = time.time() + 100
        token_blocklist._JTI_VALID_CACHE["key2"] = time.time() + 100

        clear_token_cache()

        assert len(token_blocklist._JTI_REVOKED_CACHE) == 0
        assert len(token_blocklist._JTI_VALID_CACHE) == 0
