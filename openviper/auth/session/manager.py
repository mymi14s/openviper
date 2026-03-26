"""Session lifecycle manager for OpenViper.

Provides high-level login and logout workflows, including session
rotation on login to prevent session-fixation attacks.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import Session, get_session_store
from openviper.conf import settings

logger = logging.getLogger("openviper.auth.session")


class SessionManager:
    """High-level session lifecycle management.

    Handles the login/logout workflows: creating sessions on login
    (with rotation if a session already exists) and deleting them on logout.

    Args:
        store: A session store instance. Defaults to the configured store.
    """

    def __init__(self, store: Any | None = None) -> None:
        self.store: Any = store or get_session_store()

    async def login(self, request: Any, user: Any) -> str:
        """Create (or rotate) a session for the authenticated user.

        If the request already carries a valid session cookie, the old session
        is invalidated before a new one is created (session-fixation protection).

        Args:
            request: The current request object.
            user: The authenticated user instance.

        Returns:
            The new session key.  The caller is responsible for setting
            the ``Set-Cookie`` header on the response.
        """
        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        existing_session = getattr(request, "session", None)
        existing_key = existing_session.key if existing_session else None

        if not existing_key:
            with contextlib.suppress(Exception):
                existing_key = request.cookies.get(cookie_name)

        data = {"user_id": str(user.pk)}

        if existing_key:
            session = await self.store.rotate(
                existing_key,
                user_id=user.pk,
                data=data,
            )
            # rotate returns key in some old impl, but now it returns Session
            if isinstance(session, str):
                session_key = session
                session = await self.store.load(session_key)
            else:
                session_key = session.key
        else:
            session = await self.store.create(user_id=user.pk, data=data)
            session_key = session.key

        request.user = user
        request._session = session
        # Update scope so SessionMiddleware's send_wrapper sees the new session
        scope = getattr(request, "_scope", None)
        if isinstance(scope, dict):
            scope["session"] = session
        return session_key

    async def logout(self, request: Any) -> None:
        """Invalidate the current user's session.

        Deletes the session from the store and resets ``request.user`` to
        AnonymousUser.

        Args:
            request: The current request object.
        """
        session = getattr(request, "session", None)
        if session and session.key:
            await self.store.delete(session.key)

        empty = Session(key="", store=self.store)
        request.user = AnonymousUser()
        request._session = empty
        scope = getattr(request, "_scope", None)
        if isinstance(scope, dict):
            scope["session"] = empty
