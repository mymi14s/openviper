"""Session middleware for OpenViper.

ASGI middleware that handles the session lifecycle:
1. Loads session from cookie on request.
2. Attaches session to request object.
3. Persists session changes on response.
4. Sets the session cookie on response.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import Session, get_session_store
from openviper.conf import settings
from openviper.http.request import Request

logger = logging.getLogger("openviper.auth.session")


class SessionMiddleware:
    """ASGI middleware for session management.

    Args:
        app: The next ASGI application.
        store: Optional session store instance. Defaults to the configured store.
    """

    def __init__(self, app: Any, store: Any | None = None) -> None:
        self.app = app
        self.store = store or get_session_store()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if not getattr(settings, "AUTH_SESSION_ENABLED", True):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        session_key = request.cookies.get(cookie_name)

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

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Read the CURRENT session from scope — login() may have
                # replaced it after the middleware initially ran.
                active_session = scope.get("session", session)
                await active_session.save()

                if active_session.key:
                    headers = list(message.get("headers", []))

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
