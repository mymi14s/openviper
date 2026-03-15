"""Session-based authentication backend for OpenViper."""

from __future__ import annotations

import logging
from typing import Any

from openviper.auth.sessions import get_user_from_session

logger = logging.getLogger("openviper.auth.backends.session")


class SessionBackend:
    """Authenticate requests using session cookies.

    Reads the session cookie from the ``Cookie`` header, retrieves the
    associated session from the session store, and returns the authenticated user.
    """

    async def authenticate(self, scope: dict[str, Any]) -> tuple[Any, dict[str, Any]] | None:
        """Try to authenticate a request using a session cookie.

        Args:
            scope: ASGI connection scope containing request headers.

        Returns:
            ``(user, auth_info)`` on success, ``None`` if session auth does not
            apply or fails (allowing the next backend to try).
        """
        headers = scope.get("headers", [])
        cookie_header = next((value for name, value in headers if name == b"cookie"), None)

        cookie_str = cookie_header.decode("latin-1") if cookie_header else ""
        if not cookie_str:
            return None

        try:
            user = await get_user_from_session(cookie_str)
            if user and getattr(user, "is_active", True):
                return user, {"type": "session"}
        except Exception as exc:
            logger.warning("Session authentication error: %s", exc)

        return None
