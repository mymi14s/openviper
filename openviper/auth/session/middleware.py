"""Session middleware for OpenViper.

ASGI middleware that handles the session lifecycle:
1. Loads session from cookie on request.
2. Attaches session to request object.
3. Persists session changes on response.
4. Sets the session cookie on response.

Security: Cookie values are validated to reject CR/LF characters, preventing
HTTP header injection.  The resolved user is stored in a ``contextvars`` token
so that concurrent async requests cannot bleed state.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, cast

from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import BaseSessionStore, Session, get_session_store
from openviper.conf import settings
from openviper.core.context import current_user as context_current_user
from openviper.http.request import Request

if TYPE_CHECKING:
    from openviper.auth.types import ASGIApp, ASGIMessage, ASGIReceive, ASGIScope, ASGISend

logger = logging.getLogger("openviper.auth.session")

CRLF_CHARS = frozenset("\r\n")


def is_safe_cookie_value(value: str) -> bool:
    """Reject cookie values containing CR or LF to prevent header injection."""
    return not any(c in CRLF_CHARS for c in value)


def response_sets_session_cookie(headers: list[tuple[bytes, bytes]], cookie_name: str) -> bool:
    """Return true when response headers already set the session cookie."""
    cookie_prefix = f"{cookie_name}=".encode("latin-1")
    return any(
        name.lower() == b"set-cookie" and value.startswith(cookie_prefix) for name, value in headers
    )


class SessionMiddleware:
    """ASGI middleware for session management.

    Args:
        app: The next ASGI application.
        store: Optional session store instance. Defaults to the configured store.
    """

    def __init__(self, app: ASGIApp, store: BaseSessionStore | None = None) -> None:
        self.app = app
        self.store: BaseSessionStore = store or get_session_store()

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] not in ("http",):
            await self.app(scope, receive, send)
            return

        if not getattr(settings, "AUTH_SESSION_ENABLED", True):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        session_key = request.cookies.get(cookie_name)

        # Intent: CR/LF in session keys enables HTTP header injection attacks.
        if session_key and not is_safe_cookie_value(session_key):
            logger.warning("Session cookie rejected: invalid characters in key")
            session_key = None

        session: Session | None = None
        if session_key:
            session = await self.store.load(session_key)
            logger.debug(
                "Loaded session for key %s...: %s",
                session_key[:8],
                "Found" if session else "Not Found",
            )

        if session is None:
            session = Session(key="", store=self.store)

        request._session = session
        scope["session"] = session

        if scope.get("user") is None:
            user = await self.store.get_user(session.key) if session.key else None
            logger.debug("Middleware identifying user from session: %s", user)
            scope["user"] = user or AnonymousUser()

        token = context_current_user.set(scope["user"])
        try:

            async def send_wrapper(message: ASGIMessage) -> None:
                if message["type"] == "http.response.start":
                    # Intent: Use the session produced by login during handling.
                    active_session = cast("Session", scope.get("session", session))
                    await active_session.save()

                    if active_session.key and is_safe_cookie_value(active_session.key):
                        raw_headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                        headers = list(raw_headers)
                        if response_sets_session_cookie(headers, cookie_name):
                            await send(message)
                            return

                        cookie_path = getattr(settings, "SESSION_COOKIE_PATH", "/")
                        cookie_value = f"{cookie_name}={active_session.key}; Path={cookie_path}"
                        if getattr(settings, "SESSION_COOKIE_HTTPONLY", True):
                            cookie_value += "; HttpOnly"
                        if getattr(settings, "SESSION_COOKIE_SECURE", True) or request.is_secure():
                            cookie_value += "; Secure"

                        samesite = getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax")
                        if samesite:
                            cookie_value += f"; SameSite={samesite}"

                        timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
                        if isinstance(timeout, datetime.timedelta):
                            max_age = int(timeout.total_seconds())
                        else:
                            max_age = int(timeout)
                        cookie_value += f"; Max-Age={max_age}"

                        domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
                        if domain:
                            cookie_value += f"; Domain={domain}"

                        headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                        message["headers"] = headers

                await send(message)

            await self.app(scope, receive, send_wrapper)
        finally:
            context_current_user.reset(token)
