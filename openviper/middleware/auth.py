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
        self._authenticator_classes: list[type[BaseAuthentication]] = []
        for auth_path in getattr(settings, "DEFAULT_AUTHENTICATION_CLASSES", []):
            try:
                auth_cls = import_string(auth_path)
                self._authenticator_classes.append(auth_cls)
            except Exception as exc:
                logger.error("Could not load authentication class %r: %s", auth_path, exc)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Wrap scope in a Request object for authentication classes
        request = Request(scope, receive)
        authenticators = [cls() for cls in self._authenticator_classes]
        user, auth_info = await self._authenticate(request, authenticators)

        scope["user"] = user
        scope["auth"] = auth_info

        token = context_current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            context_current_user.reset(token)

    async def _authenticate(
        self, request: Request, authenticators: list[BaseAuthentication]
    ) -> tuple[Any, Any]:
        """Try each configured authentication scheme in order.

        Returns:
            ``(user, auth_info)`` tuple.  ``user`` is :class:`AnonymousUser`
            if no scheme succeeds.
        """
        for authenticator in authenticators:
            try:
                result = await authenticator.authenticate(request)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning(
                    "Authentication error with %s: %s", authenticator.__class__.__name__, exc
                )

        return AnonymousUser(), {"type": "none"}
