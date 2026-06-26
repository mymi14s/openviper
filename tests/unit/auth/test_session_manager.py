"""Unit tests for modernized session manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.hooks import auth_hooks
from openviper.auth.models import AnonymousUser
from openviper.auth.request_state import set_auth_state
from openviper.auth.session.manager import SessionManager
from openviper.auth.session.store import Session


@pytest.fixture(autouse=True)
def clear_auth_hooks():
    auth_hooks.clear()
    yield
    auth_hooks.clear()


class TestSessionManager:
    @pytest.fixture
    def mock_store(self):
        store = MagicMock()
        store.create = AsyncMock()
        store.rotate = AsyncMock()
        store.delete = AsyncMock()
        return store

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.cookies = {}
        request.session = Session(key="", store=None)
        request.state = {}
        return request

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.pk = 42
        return user

    @pytest.mark.asyncio
    async def test_login_creates_new_session(self, mock_store, mock_request, mock_user):
        manager = SessionManager(store=mock_store)
        mock_session = Session(key="new-key", data={}, store=mock_store)
        mock_store.create.return_value = mock_session
        calls = []

        @auth_hooks.before_login
        def before_login(context):
            calls.append(("before", context.user))

        @auth_hooks.on_login
        async def on_login(context):
            calls.append(("after", context.session))

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            session_key = await manager.login(mock_request, mock_user)

        assert session_key == "new-key"
        assert mock_request.user == mock_user
        assert mock_request._session is mock_session
        assert calls == [("before", mock_user), ("after", mock_session)]
        mock_store.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_reuses_view_context_without_duplicate_before_hook(
        self, mock_store, mock_request, mock_user
    ):
        manager = SessionManager(store=mock_store)
        mock_session = Session(key="new-key", data={}, store=mock_store)
        mock_store.create.return_value = mock_session
        calls = []

        @auth_hooks.before_login
        def before_login(context):
            calls.append("before")

        @auth_hooks.on_login
        def on_login(context):
            calls.append(context.auth_backend)

        set_auth_state(mock_request, "before_login_hook_ran", True)

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            await manager.login(mock_request, mock_user)

        assert calls == ["session"]

    @pytest.mark.asyncio
    async def test_login_updates_scope_session(self, mock_store, mock_user):
        """login() must update scope['session'] so the middleware cookie is correct."""
        scope = {"type": "http", "method": "POST", "path": "/login", "headers": []}
        request = MagicMock()
        request._scope = scope
        request.cookies = {}
        request.session = Session(key="", store=None)

        manager = SessionManager(store=mock_store)
        mock_session = Session(key="new-key", data={}, store=mock_store)
        mock_store.create.return_value = mock_session

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            await manager.login(request, mock_user)

        assert scope["session"] is mock_session

    @pytest.mark.asyncio
    async def test_login_rotates_existing_session(self, mock_store, mock_user):
        request = MagicMock()
        request.session = Session(key="old-key", data={}, store=mock_store)
        request.cookies = {"sessionid": "old-key"}

        manager = SessionManager(store=mock_store)
        mock_session = Session(key="rotated-key", data={}, store=mock_store)
        mock_store.rotate.return_value = mock_session

        with patch("openviper.auth.session.manager.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            session_key = await manager.login(request, mock_user)

        assert session_key == "rotated-key"
        mock_store.rotate.assert_called_once_with("old-key", user_id=42, data={"user_id": "42"})

    @pytest.mark.asyncio
    async def test_logout_deletes_session(self, mock_store):
        # Use a mock that behaves a bit more like our Request object
        class MockRequest:
            def __init__(self, session):
                self._session = session
                self.user = MagicMock()

            @property
            def session(self):
                return self._session

            @session.setter
            def session(self, value):  # Not used in code but for completeness
                self._session = value

        initial_session = Session(key="session-to-delete", data={}, store=mock_store)
        request = MockRequest(initial_session)
        original_user = request.user

        calls = []

        @auth_hooks.on_logout
        def on_logout(context):
            calls.append((context.user, context.session))

        response = MagicMock()
        manager = SessionManager(store=mock_store)
        await manager.logout(request, response=response)

        mock_store.delete.assert_called_once_with("session-to-delete")
        assert isinstance(request.user, AnonymousUser)
        assert request.session.key == ""
        response.delete_cookie.assert_called_once()
        assert calls == [(original_user, initial_session)]
