"""Authentication middleware for configured backends."""

from __future__ import annotations

import logging

from openviper.auth.manager import AuthManager
from openviper.core.context import current_user as context_current_user
from openviper.middleware.base import ASGIApp, BaseMiddleware

logger = logging.getLogger("openviper.auth")


class AuthenticationMiddleware(BaseMiddleware):
    """Attach authenticated user and auth metadata to request scope."""

    def __init__(self, app: ASGIApp, manager: AuthManager | None = None) -> None:
        super().__init__(app)
        if manager is None:
            manager = AuthManager()
        self._manager = manager

    async def __call__(
        self,
        scope: dict[str, object],
        receive: object,
        send: object,
    ) -> None:
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
