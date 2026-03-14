"""Unit tests for openviper.auth.session.middleware module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.auth.models import AnonymousUser
from openviper.auth.session.middleware import SessionMiddleware
from openviper.auth.session.store import DatabaseSessionStore


class TestSessionMiddleware:
    """Tests for SessionMiddleware class."""

    @pytest.fixture
    def mock_store(self):
        """Create a mock session store."""
        store = MagicMock()
        store.get_user = AsyncMock(return_value=None)
        return store

    @pytest.fixture
    def mock_app(self):
        """Create a mock ASGI app."""
        return AsyncMock()

    def test_init_with_custom_store(self, mock_app, mock_store):

        middleware = SessionMiddleware(mock_app, store=mock_store)
        assert middleware.store is mock_store
        assert middleware.app is mock_app

    def test_init_creates_default_store(self, mock_app):

        middleware = SessionMiddleware(mock_app)
        assert isinstance(middleware.store, DatabaseSessionStore)

    @pytest.mark.asyncio
    async def test_passes_through_non_http_types(self, mock_app, mock_store):

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        mock_app.assert_called_once_with(scope, receive, send)
        mock_store.get_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_anonymous_user_when_no_cookie(self, mock_app, mock_store):

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {"type": "http", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert isinstance(scope["user"], AnonymousUser)
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_user_from_session(self, mock_app, mock_store):

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_store.get_user = AsyncMock(return_value=mock_user)

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {
            "type": "http",
            "headers": [(b"cookie", b"sessionid=test-session-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert scope["user"] is mock_user

    @pytest.mark.asyncio
    async def test_sets_anonymous_for_inactive_user(self, mock_app, mock_store):

        inactive_user = MagicMock()
        inactive_user.is_active = False
        mock_store.get_user = AsyncMock(return_value=inactive_user)

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {
            "type": "http",
            "headers": [(b"cookie", b"sessionid=test-session-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert isinstance(scope["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_handles_store_exception(self, mock_app, mock_store):

        mock_store.get_user = AsyncMock(side_effect=Exception("Store error"))

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {
            "type": "http",
            "headers": [(b"cookie", b"sessionid=test-session-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should fall back to anonymous user and still call app
        assert isinstance(scope["user"], AnonymousUser)
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_preserves_existing_user(self, mock_app, mock_store):

        existing_user = MagicMock()

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {
            "type": "http",
            "headers": [],
            "user": existing_user,  # Already set
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # setdefault doesn't overwrite existing user
        assert scope["user"] is existing_user

    @pytest.mark.asyncio
    async def test_works_with_websocket(self, mock_app, mock_store):

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_store.get_user = AsyncMock(return_value=mock_user)

        middleware = SessionMiddleware(mock_app, store=mock_store)

        scope = {
            "type": "websocket",
            "headers": [(b"cookie", b"sessionid=test-session-key")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert scope["user"] is mock_user
