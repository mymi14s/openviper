"""Session middleware for OpenViper.

Lightweight ASGI middleware that reads the session cookie and populates
``scope["user"]`` from the session store.  Suitable for use in middleware
stacks that do not need the full JWT + session pipeline provided by
:class:`~openviper.middleware.auth.AuthenticationMiddleware`.
"""

from __future__ import annotations

import logging
from typing import Any

from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import DatabaseSessionStore

logger = logging.getLogger("openviper.auth.session")


class SessionMiddleware:
    """ASGI middleware that authenticates requests via session cookies.

    Reads the configured ``SESSION_COOKIE_NAME`` cookie, looks up the session in
    the store, and sets ``scope["user"]``.  Falls back to
    :class:`~openviper.auth.models.AnonymousUser` when no valid session is found.

    This middleware does **not** handle JWT tokens.  Use
    :class:`~openviper.auth.middleware.AuthenticationMiddleware` (which delegates
    to :class:`~openviper.auth.manager.AuthManager`) if you need both JWT and
    session support.

    Args:
        app: The next ASGI application.
        store: Optional :class:`~openviper.auth.session.store.DatabaseSessionStore`
               instance.  Defaults to a fresh ``DatabaseSessionStore``.

    Example::

        app = SessionMiddleware(app)
    """

    def __init__(self, app: Any, store: Any | None = None) -> None:
        self.app = app
        if store is None:

            store = DatabaseSessionStore()
        self.store = store

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cookie_header = b""
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                cookie_header = value
                break

        user: Any = AnonymousUser()
        if cookie_header:
            try:
                cookie_str = cookie_header.decode("latin-1")
                result = await self.store.get_user(cookie_str)
                if result and getattr(result, "is_active", True):
                    user = result
            except Exception as exc:
                logger.warning("Session middleware error: %s", exc)

        scope.setdefault("user", user)
        await self.app(scope, receive, send)
