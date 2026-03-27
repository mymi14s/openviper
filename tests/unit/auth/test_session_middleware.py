"""Unit tests for modernized session middleware."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.models import AnonymousUser
from openviper.auth.session.middleware import SessionMiddleware
from openviper.auth.session.store import Session


class TestSessionMiddleware:
    @pytest.fixture
    def mock_store(self):
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        store.get_user = AsyncMock(return_value=None)
        return store

    @pytest.fixture
    def mock_app(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_sets_anonymous_user_when_no_cookie(self, mock_app, mock_store):
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert isinstance(scope["user"], AnonymousUser)
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_loads_session_from_cookie(self, mock_app, mock_store):
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"sessionid=test-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_session = Session(key="test-key", data={"user_id": "1"}, store=mock_store)
        mock_store.load.return_value = mock_session

        mock_user = MagicMock()
        mock_store.get_user.return_value = mock_user

        await middleware(scope, receive, send)

        assert scope["session"] == mock_session
        assert scope["user"] == mock_user

    @pytest.mark.asyncio
    async def test_sets_anonymous_for_invalid_session(self, mock_app, mock_store):
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"sessionid=invalid-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_store.load.return_value = None

        await middleware(scope, receive, send)

        assert isinstance(scope["user"], AnonymousUser)
        assert scope["session"].key == ""

    @pytest.mark.asyncio
    async def test_saves_session_on_response(self, mock_app, mock_store):
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"sessionid=test-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_session = MagicMock(spec=Session)
        mock_session.key = "test-key"
        mock_session.save = AsyncMock()
        mock_store.load.return_value = mock_session

        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        mock_app.side_effect = mock_app_call

        await middleware(scope, receive, send)

        mock_session.save.assert_called_once()
        sent_message = send.call_args[0][0]
        headers = dict(sent_message["headers"])
        assert b"set-cookie" in headers
        assert b"sessionid=test-key" in headers[b"set-cookie"]

    @pytest.mark.asyncio
    async def test_session_cookie_has_max_age(self, mock_app, mock_store):
        """Session cookie should include Max-Age derived from SESSION_TIMEOUT."""
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"sessionid=test-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_session = MagicMock(spec=Session)
        mock_session.key = "test-key"
        mock_session.save = AsyncMock()
        mock_store.load.return_value = mock_session

        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        mock_app.side_effect = mock_app_call

        with patch("openviper.auth.session.middleware.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            mock_settings.SESSION_COOKIE_SECURE = False
            mock_settings.SESSION_COOKIE_SAMESITE = "Lax"
            mock_settings.SESSION_TIMEOUT = datetime.timedelta(hours=1)
            mock_settings.SESSION_COOKIE_DOMAIN = None

            await middleware(scope, receive, send)

        sent_message = send.call_args[0][0]
        cookie_header = dict(sent_message["headers"])[b"set-cookie"].decode("latin-1")
        assert "Max-Age=3600" in cookie_header

    @pytest.mark.asyncio
    async def test_session_cookie_domain(self, mock_app, mock_store):
        """Session cookie should include Domain when SESSION_COOKIE_DOMAIN is set."""
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"sessionid=test-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        mock_session = MagicMock(spec=Session)
        mock_session.key = "test-key"
        mock_session.save = AsyncMock()
        mock_store.load.return_value = mock_session

        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        mock_app.side_effect = mock_app_call

        with patch("openviper.auth.session.middleware.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            mock_settings.SESSION_COOKIE_SECURE = False
            mock_settings.SESSION_COOKIE_SAMESITE = "Lax"
            mock_settings.SESSION_TIMEOUT = datetime.timedelta(hours=1)
            mock_settings.SESSION_COOKIE_DOMAIN = ".example.com"

            await middleware(scope, receive, send)

        sent_message = send.call_args[0][0]
        cookie_header = dict(sent_message["headers"])[b"set-cookie"].decode("latin-1")
        assert "Domain=.example.com" in cookie_header

    @pytest.mark.asyncio
    async def test_passthrough_non_http(self, mock_app, mock_store):
        """Non-HTTP scopes should pass through without session handling."""
        middleware = SessionMiddleware(mock_app, store=mock_store)
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        mock_app.assert_called_once_with(scope, receive, send)
        mock_store.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_cookie_set_when_login_updates_scope_session(self, mock_store):
        """After login replaces scope['session'], the middleware must write
        the new session's cookie — not the stale empty one from request start."""
        new_session = Session(key="new-session-key", data={"user_id": "42"}, store=mock_store)

        async def app_that_simulates_login(scope, receive, send):
            # Simulate what login() does: replace scope["session"]
            scope["session"] = new_session
            await send({"type": "http.response.start", "status": 302, "headers": []})

        middleware = SessionMiddleware(app_that_simulates_login, store=mock_store)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/login",
            "headers": [],  # No existing session cookie
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        sent_message = send.call_args[0][0]
        headers = dict(sent_message["headers"])
        assert b"set-cookie" in headers
        cookie = headers[b"set-cookie"].decode("latin-1")
        assert "sessionid=new-session-key" in cookie
