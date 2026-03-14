"""Session store for OpenViper.

Provides a class-based interface over the low-level session functions
in :mod:`openviper.auth.sessions`.
"""

from __future__ import annotations

from typing import Any

from openviper.auth.sessions import (
    create_session,
    delete_session,
    generate_session_key,
    get_user_from_session,
)


class DatabaseSessionStore:
    """Database-backed session store.

    Wraps the low-level session functions with a higher-level class API,
    supporting create, retrieve, delete, and rotate operations.

    Example::

        store = DatabaseSessionStore()
        session_key = await store.create(user_id=42)
        user = await store.get_user("sessionid=<key>")
        await store.delete(session_key)
        new_key = await store.rotate(session_key, user_id=42)
    """

    async def create(self, user_id: Any, data: dict[str, Any] | None = None) -> str:
        """Create a new session for the given user.

        Args:
            user_id: Primary key of the authenticated user.
            data: Optional extra data to persist in the session.

        Returns:
            The new session key (store in a cookie).
        """
        return await create_session(user_id=user_id, data=data)

    async def get_user(self, cookie_header: str) -> Any | None:
        """Retrieve the user for the session identified by the cookie header.

        Args:
            cookie_header: Raw ``Cookie`` header value.

        Returns:
            Authenticated user instance, or ``None`` if not found / expired.
        """
        return await get_user_from_session(cookie_header)

    async def delete(self, session_key: str) -> None:
        """Delete a session, invalidating it immediately.

        Args:
            session_key: The session key to delete.
        """
        await delete_session(session_key)

    async def rotate(
        self,
        session_key: str,
        user_id: Any,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Invalidate the old session and create a fresh one (session rotation).

        Used on login to prevent session-fixation attacks.

        Args:
            session_key: The existing session key to invalidate.
            user_id: Primary key of the authenticated user.
            data: Optional extra data to persist in the new session.

        Returns:
            The new session key.
        """
        await delete_session(session_key)
        return await create_session(user_id=user_id, data=data)

    def generate_key(self) -> str:
        """Generate a new random session key without persisting it.

        Returns:
            A cryptographically random URL-safe token string.
        """
        return generate_session_key()
