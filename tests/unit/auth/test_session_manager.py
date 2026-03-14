"""Unit tests for openviper.auth.session.manager module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.models import AnonymousUser
from openviper.auth.session.manager import SessionManager
from openviper.auth.session.store import DatabaseSessionStore


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.fixture
    def mock_store(self):
        """Create a mock session store."""
        store = MagicMock()
        store.create = AsyncMock(return_value="new-session-key")
        store.rotate = AsyncMock(return_value="rotated-session-key")
        store.delete = AsyncMock()
        return store

    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""
        request = MagicMock()
        request.cookies = {}
        return request

    @pytest.fixture
    def mock_user(self):
        """Create a mock user."""
        user = MagicMock()
        user.pk = 42
        return user

    def test_init_with_custom_store(self, mock_store):

        manager = SessionManager(store=mock_store)
        assert manager.store is mock_store

    def test_init_creates_default_store(self):

        manager = SessionManager()
        assert isinstance(manager.store, DatabaseSessionStore)

    @pytest.mark.asyncio
    async def test_login_creates_new_session(self, mock_store, mock_request, mock_user):

        manager = SessionManager(store=mock_store)

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            session_key = await manager.login(mock_request, mock_user)

        assert session_key == "new-session-key"
        assert mock_request.user is mock_user
        mock_store.create.assert_called_once_with(user_id=42, data={"user_id": 42})

    @pytest.mark.asyncio
    async def test_login_rotates_existing_session(self, mock_store, mock_user):

        request = MagicMock()
        request.cookies = {"sessionid": "old-session-key"}

        manager = SessionManager(store=mock_store)

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            session_key = await manager.login(request, mock_user)

        assert session_key == "rotated-session-key"
        mock_store.rotate.assert_called_once_with(
            "old-session-key", user_id=42, data={"user_id": 42}
        )

    @pytest.mark.asyncio
    async def test_logout_deletes_session(self, mock_store):

        request = MagicMock()
        request.cookies = {"sessionid": "session-to-delete"}
        request.user = MagicMock()

        manager = SessionManager(store=mock_store)

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            await manager.logout(request)

        mock_store.delete.assert_called_once_with("session-to-delete")
        assert isinstance(request.user, AnonymousUser)

    @pytest.mark.asyncio
    async def test_logout_handles_no_session(self, mock_store):

        request = MagicMock()
        request.cookies = {}

        manager = SessionManager(store=mock_store)

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            await manager.logout(request)

        mock_store.delete.assert_not_called()
        assert isinstance(request.user, AnonymousUser)


class TestDatabaseSessionStore:
    """Tests for DatabaseSessionStore class."""

    @pytest.fixture
    def store(self):

        return DatabaseSessionStore()

    @pytest.mark.asyncio
    async def test_create_calls_create_session(self, store):
        with patch(
            "openviper.auth.session.store.create_session",
            new=AsyncMock(return_value="test-key"),
        ):
            result = await store.create(user_id=42, data={"extra": "data"})

        assert result == "test-key"

    @pytest.mark.asyncio
    async def test_get_user_calls_get_user_from_session(self, store):
        mock_user = MagicMock()
        with patch(
            "openviper.auth.session.store.get_user_from_session",
            new=AsyncMock(return_value=mock_user),
        ):
            result = await store.get_user("sessionid=abc123")

        assert result is mock_user

    @pytest.mark.asyncio
    async def test_delete_calls_delete_session(self, store):
        with patch("openviper.auth.session.store.delete_session", new=AsyncMock()) as mock_delete:
            await store.delete("session-key")

        mock_delete.assert_called_once_with("session-key")

    @pytest.mark.asyncio
    async def test_rotate_deletes_old_and_creates_new(self, store):
        with patch("openviper.auth.session.store.delete_session", new=AsyncMock()) as mock_delete:
            with patch(
                "openviper.auth.session.store.create_session",
                new=AsyncMock(return_value="new-key"),
            ):
                result = await store.rotate("old-key", user_id=42, data={"extra": "data"})

        mock_delete.assert_called_once_with("old-key")
        assert result == "new-key"

    def test_generate_key_returns_random_string(self, store):
        key1 = store.generate_key()
        key2 = store.generate_key()

        assert key1 != key2
        assert len(key1) > 0
