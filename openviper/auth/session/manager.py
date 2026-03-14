"""Session lifecycle manager for OpenViper.

Provides high-level login and logout workflows, including session
rotation on login to prevent session-fixation attacks.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import DatabaseSessionStore
from openviper.conf import settings

logger = logging.getLogger("openviper.auth.session")


class SessionManager:
    """High-level session lifecycle management.

    Handles the login/logout workflows: creating sessions on login
    (with rotation if a session already exists) and deleting them on logout.

    Args:
        store: A :class:`~openviper.auth.session.store.DatabaseSessionStore`
               instance.  Defaults to a fresh ``DatabaseSessionStore``.

    Example::

        manager = SessionManager()
        session_key = await manager.login(request, user)
        await manager.logout(request)
    """

    def __init__(self, store: Any | None = None) -> None:
        if store is None:

            store = DatabaseSessionStore()
        self.store = store

    async def login(self, request: Any, user: Any) -> str:
        """Create (or rotate) a session for the authenticated user.

        If the request already carries a valid session cookie, the old session
        is invalidated before a new one is created (session-fixation protection).

        Args:
            request: The current request object (must have a ``cookies`` mapping).
            user: The authenticated user instance.

        Returns:
            The new session key.  The caller is responsible for setting
            the ``Set-Cookie`` header on the response.
        """

        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        existing_key: str | None = None
        with contextlib.suppress(Exception):
            existing_key = request.cookies.get(cookie_name)

        data = {"user_id": user.pk}
        if existing_key:
            session_key = await self.store.rotate(
                existing_key,
                user_id=user.pk,
                data=data,
            )
        else:
            session_key = await self.store.create(user_id=user.pk, data=data)

        request.user = user
        return session_key

    async def logout(self, request: Any) -> None:
        """Invalidate the current user's session.

        Deletes the session from the store and resets ``request.user`` to
        :class:`~openviper.auth.models.AnonymousUser`.

        Args:
            request: The current request object (must have a ``cookies`` mapping).
        """

        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        session_key: str | None = None
        with contextlib.suppress(Exception):
            session_key = request.cookies.get(cookie_name)

        if session_key:
            await self.store.delete(session_key)

        request.user = AnonymousUser()
