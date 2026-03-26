"""Session management for OpenViper (Compatibility Layer).

Delegates to the configured session store via ``get_session_store()``.
"""

from __future__ import annotations

import logging
import secrets
from http.cookies import SimpleCookie
from typing import Any

from openviper.auth.session.store import (
    _SESSION_CACHE_PREFIX,
    _SESSION_USER_CACHE_PREFIX,
    get_session_store,
)
from openviper.cache import get_cache
from openviper.conf import settings

logger = logging.getLogger("openviper.auth.sessions")


def generate_session_key() -> str:
    """Generate a cryptographically secure URL-safe session key."""
    return secrets.token_urlsafe(48)


async def create_session(user_id: Any, data: dict[str, Any] | None = None) -> str:
    """Create a new session for the given user."""
    store = get_session_store()
    session = await store.create(user_id, data)
    return session.key


async def get_user_from_session(cookie_header: str) -> Any | None:
    """Parse the cookie header and look up the user from the session store."""
    try:
        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
    except Exception:
        cookie_name = "sessionid"

    cookie = SimpleCookie()
    cookie.load(cookie_header)
    session_key = cookie.get(cookie_name)
    if not session_key:
        return None

    store = get_session_store()
    return await store.get_user(session_key.value)


async def delete_session(session_key: str) -> None:
    """Invalidate a session (logout)."""
    store = get_session_store()
    await store.delete(session_key)


async def clear_session_cache() -> None:
    """Clear only session-related cached data (prefixed keys).

    Does *not* call ``cache.clear()`` which would wipe unrelated entries
    such as permission caches or rate-limiting counters.
    """
    cache = get_cache()
    for prefix in (_SESSION_CACHE_PREFIX, _SESSION_USER_CACHE_PREFIX):
        for key in await cache.keys(prefix):
            await cache.delete(key)
