"""Unit tests for session store caching behaviour."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.session.store import DatabaseSessionStore


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    return cache


@pytest.fixture
def mock_engine():
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.begin = MagicMock(return_value=mock_context)
    engine.connect = MagicMock(return_value=mock_context)
    return engine, mock_conn


class TestSessionStoreCache:
    @pytest.mark.asyncio
    async def test_load_caches_session_data(self, mock_cache, mock_engine) -> None:
        """Load should cache session data after a DB fetch."""
        engine, mock_conn = mock_engine

        mock_row = MagicMock()
        mock_row.data = '{"user_id": "1"}'
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        key = "a" * 64

        with patch("openviper.auth.session.store._ensure_table", new=AsyncMock()):
            with patch(
                "openviper.auth.session.store.get_engine", new=AsyncMock(return_value=engine)
            ):
                with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
                    store = DatabaseSessionStore()
                    session = await store.load(key)

        assert session is not None
        assert session.key == key
        mock_cache.set.assert_called_once()
        set_call = mock_cache.set.call_args
        assert set_call[0][0] == f"session:{key}"
        assert set_call[0][1] == {"user_id": "1"}

    @pytest.mark.asyncio
    async def test_load_returns_from_cache_on_hit(self, mock_cache) -> None:
        """Second load should return cached data without DB query."""
        key = "b" * 64
        mock_cache.get.return_value = {"user_id": "2"}

        with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
            store = DatabaseSessionStore()
            session = await store.load(key)

        assert session is not None
        assert session.key == key
        assert session.get("user_id") == "2"

    @pytest.mark.asyncio
    async def test_save_updates_cache(self, mock_cache, mock_engine) -> None:
        """Save should update the cache with new data."""
        engine, mock_conn = mock_engine
        key = "c" * 64

        with patch("openviper.auth.session.store._ensure_table", new=AsyncMock()):
            with patch(
                "openviper.auth.session.store.get_engine", new=AsyncMock(return_value=engine)
            ):
                with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
                    store = DatabaseSessionStore()
                    await store.save(key, {"user_id": "3"})

        mock_cache.set.assert_called_once()
        set_call = mock_cache.set.call_args
        assert set_call[0][0] == f"session:{key}"
        assert set_call[0][1] == {"user_id": "3"}

    @pytest.mark.asyncio
    async def test_delete_invalidates_cache(self, mock_cache, mock_engine) -> None:
        """Delete should remove both session and user cache entries."""
        engine, mock_conn = mock_engine
        key = "d" * 64

        with patch("openviper.auth.session.store._ensure_table", new=AsyncMock()):
            with patch(
                "openviper.auth.session.store.get_engine", new=AsyncMock(return_value=engine)
            ):
                with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
                    store = DatabaseSessionStore()
                    await store.delete(key)

        assert mock_cache.delete.call_count == 2
        deleted_keys = [call[0][0] for call in mock_cache.delete.call_args_list]
        assert f"session:{key}" in deleted_keys
        assert f"session_user:{key}" in deleted_keys

    @pytest.mark.asyncio
    async def test_get_user_caches_user_id(self, mock_cache, mock_engine) -> None:
        """get_user should cache the user_id for future lookups."""
        engine, mock_conn = mock_engine
        key = "e" * 64

        mock_row = MagicMock()
        mock_row.user_id = "42"
        mock_row.expires_at = MagicMock()
        mock_row.expires_at.__lt__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        fake_user = MagicMock()

        with patch("openviper.auth.session.store._ensure_table", new=AsyncMock()):
            with patch(
                "openviper.auth.session.store.get_engine", new=AsyncMock(return_value=engine)
            ):
                with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
                    with patch(
                        "openviper.auth.session.store.get_user_by_id",
                        new=AsyncMock(return_value=fake_user),
                    ):
                        store = DatabaseSessionStore()
                        user = await store.get_user(key)

        assert user is fake_user
        mock_cache.set.assert_called_once()
        set_call = mock_cache.set.call_args
        assert set_call[0][0] == f"session_user:{key}"
        assert set_call[0][1] == "42"

    @pytest.mark.asyncio
    async def test_get_user_uses_cached_user_id(self, mock_cache) -> None:
        """get_user should use cached user_id without DB query."""
        key = "f" * 64
        mock_cache.get.return_value = "42"

        fake_user = MagicMock()

        with patch("openviper.auth.session.store.get_cache", return_value=mock_cache):
            with patch(
                "openviper.auth.session.store.get_user_by_id", new=AsyncMock(return_value=fake_user)
            ):
                store = DatabaseSessionStore()
                user = await store.get_user(key)

        assert user is fake_user
