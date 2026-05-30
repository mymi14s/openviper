"""Unit tests for openviper.auth.middleware module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.middleware import AuthenticationMiddleware


class TestAuthenticationMiddleware:
    """Tests for AuthenticationMiddleware."""

    @pytest.mark.asyncio
    async def test_authenticates_http_requests(self):
        """Should authenticate HTTP requests."""
        mock_app = AsyncMock()
        mock_manager = MagicMock()
        mock_user = MagicMock()
        mock_manager.authenticate = AsyncMock(return_value=(mock_user, {"method": "jwt"}))

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "http"}
        receive = MagicMock()
        send = MagicMock()

        await middleware(scope, receive, send)

        assert scope["user"] is mock_user
        assert scope["auth"] == {"method": "jwt"}
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticates_websocket_requests(self):
        """Should authenticate WebSocket requests."""
        mock_app = AsyncMock()
        mock_manager = MagicMock()
        mock_user = MagicMock()
        mock_manager.authenticate = AsyncMock(return_value=(mock_user, {"method": "session"}))

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "websocket"}
        receive = MagicMock()
        send = MagicMock()

        await middleware(scope, receive, send)

        assert scope["user"] is mock_user
        assert scope["auth"] == {"method": "session"}

    @pytest.mark.asyncio
    async def test_skips_non_http_websocket_requests(self):
        """Should skip authentication for other request types."""
        mock_app = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.authenticate = AsyncMock()

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "lifespan"}
        receive = MagicMock()
        send = MagicMock()

        await middleware(scope, receive, send)

        mock_manager.authenticate.assert_not_called()
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_default_manager_when_none_provided(self):
        """Should create default AuthManager when none provided."""
        mock_app = AsyncMock()

        with patch("openviper.auth.middleware.AuthManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.authenticate = AsyncMock(return_value=(MagicMock(), {}))
            mock_manager_class.return_value = mock_manager

            middleware = AuthenticationMiddleware(mock_app)

            scope = {"type": "http"}
            receive = MagicMock()
            send = MagicMock()

            await middleware(scope, receive, send)

            mock_manager_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_user_in_context(self):
        """Should set user in context variable."""
        mock_app = AsyncMock()
        mock_manager = MagicMock()
        mock_user = MagicMock()
        mock_manager.authenticate = AsyncMock(return_value=(mock_user, {}))

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "http"}
        receive = MagicMock()
        send = MagicMock()

        with patch("openviper.auth.middleware.context_current_user") as mock_context:
            mock_token = MagicMock()
            mock_context.set.return_value = mock_token

            await middleware(scope, receive, send)

            mock_context.set.assert_called_once_with(mock_user)
            mock_context.reset.assert_called_once_with(mock_token)

    @pytest.mark.asyncio
    async def test_resets_context_after_request(self):
        """Should reset context after request is processed."""
        mock_app = AsyncMock()
        mock_manager = MagicMock()
        mock_user = MagicMock()
        mock_manager.authenticate = AsyncMock(return_value=(mock_user, {}))

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "http"}
        receive = MagicMock()
        send = MagicMock()

        with patch("openviper.auth.middleware.context_current_user") as mock_context:
            mock_token = MagicMock()
            mock_context.set.return_value = mock_token

            await middleware(scope, receive, send)

            # Should reset context even after normal execution
            mock_context.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_context_on_exception(self):
        """Should reset context even when exception occurs."""
        mock_app = AsyncMock(side_effect=Exception("Test error"))
        mock_manager = MagicMock()
        mock_user = MagicMock()
        mock_manager.authenticate = AsyncMock(return_value=(mock_user, {}))

        middleware = AuthenticationMiddleware(mock_app, manager=mock_manager)

        scope = {"type": "http"}
        receive = MagicMock()
        send = MagicMock()

        with patch("openviper.auth.middleware.context_current_user") as mock_context:
            mock_token = MagicMock()
            mock_context.set.return_value = mock_token

            with pytest.raises(Exception, match="Test error"):
                await middleware(scope, receive, send)

            # Should reset context even after exception
            mock_context.reset.assert_called_once()
