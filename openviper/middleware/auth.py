import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.auth.authentications import BaseAuthentication

from openviper.auth.models import AnonymousUser
from openviper.conf import settings
from openviper.core.context import current_user as context_current_user
from openviper.http.request import Request
from openviper.middleware.base import ASGIApp, BaseMiddleware
from openviper.utils.importlib import import_string

logger = logging.getLogger("openviper.auth")


class AuthenticationMiddleware(BaseMiddleware):
    """Identify the authenticated user using pluggable authentication schemes.

    Iterates through ``settings.DEFAULT_AUTHENTICATION_CLASSES`` to determine
    the current user.  Sets ``scope["user"]`` and ``scope["auth"]`` for
    downstream handlers.

    Args:
        app: Next ASGI app.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._authenticators_cache: list[BaseAuthentication] | None = None

    @property
    def authenticators(self) -> list[BaseAuthentication]:
        """Load and instantiate authentication classes once."""
        if self._authenticators_cache is None:
            self._authenticators_cache = []
            for auth_path in getattr(settings, "DEFAULT_AUTHENTICATION_CLASSES", []):
                try:
                    auth_cls = import_string(auth_path)
                    self._authenticators_cache.append(auth_cls())
                except Exception as exc:
                    logger.error("Could not load authentication class %r: %s", auth_path, exc)
        return self._authenticators_cache

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Wrap scope in a Request object for authentication classes
        request = Request(scope, receive)
        user, auth_info = await self._authenticate(request)

        scope["user"] = user
        scope["auth"] = auth_info

        token = context_current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            context_current_user.reset(token)

    async def _authenticate(self, request: Request) -> tuple[Any, Any]:
        """Try each configured authentication scheme in order.

        Returns:
            ``(user, auth_info)`` tuple.  ``user`` is :class:`AnonymousUser`
            if no scheme succeeds.
        """
        for authenticator in self.authenticators:
            try:
                result = await authenticator.authenticate(request)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning(
                    "Authentication error with %s: %s", authenticator.__class__.__name__, exc
                )

        return AnonymousUser(), {"type": "none"}
