"""Authentication middleware for openviper.auth.

Uses :class:`~openviper.auth.manager.AuthManager` with pluggable backends to
authenticate each request and attach the resolved user to ``scope["user"]``.

This is the recommended middleware for new projects.  It is equivalent in
behaviour to :class:`~openviper.middleware.auth.AuthenticationMiddleware` but
delegates all auth logic to the configurable backend pipeline instead of
hard-coding JWT + session handling.

Example::

    from openviper.auth.middleware import AuthenticationMiddleware

    app = AuthenticationMiddleware(app)
"""

from __future__ import annotations

import logging
from typing import Any

from openviper.auth.manager import AuthManager
from openviper.core.context import current_user as context_current_user
from openviper.middleware.base import ASGIApp, BaseMiddleware

logger = logging.getLogger("openviper.auth")


class AuthenticationMiddleware(BaseMiddleware):
    """Authenticate requests using the pluggable :class:`~openviper.auth.manager.AuthManager`.

    Sets ``scope["user"]`` and ``scope["auth"]`` for downstream handlers.
    If no credentials are present (or all backends fail), sets an
    :class:`~openviper.auth.models.AnonymousUser`.

    Args:
        app: The next ASGI application.
        manager: Optional pre-configured :class:`~openviper.auth.manager.AuthManager`.
            Defaults to a new manager built from the ``AUTH_BACKENDS`` setting.

    Example::

        app = AuthenticationMiddleware(app)
        # or with a custom backend list:
        from openviper.auth.backends.jwt_backend import JWTBackend
        app = AuthenticationMiddleware(app, manager=AuthManager([JWTBackend()]))
    """

    def __init__(self, app: ASGIApp, manager: Any | None = None) -> None:
        super().__init__(app)
        if manager is None:
            manager = AuthManager()
        self._manager = manager

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        user, auth_info = await self._manager.authenticate(scope)
        scope["user"] = user
        scope["auth"] = auth_info

        token = context_current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            context_current_user.reset(token)
