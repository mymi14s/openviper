"""Authentication schemes for OpenViper, inspired by Django Rest Framework."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Final

from openviper.auth.jwt import decode_access_token
from openviper.auth.session.store import get_session_store
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.conf import settings
from openviper.exceptions import TokenExpired

if TYPE_CHECKING:
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth")

# ---------------------------------------------------------------------------
# Module-level TTL user cache (moved from middleware for reuse)
# ---------------------------------------------------------------------------

_USER_CACHE: dict[int, tuple[Any, float]] = {}
_USER_CACHE_LOCK: Any = None
_USER_CACHE_TTL: Final[float] = 30.0
_USER_CACHE_MAXSIZE: Final[int] = 4096
_LOCK_INIT_GUARD = threading.Lock()


def _get_user_cache_lock() -> Any:
    global _USER_CACHE_LOCK
    if _USER_CACHE_LOCK is None:
        with _LOCK_INIT_GUARD:
            if _USER_CACHE_LOCK is None:
                _USER_CACHE_LOCK = asyncio.Lock()
    return _USER_CACHE_LOCK


async def get_user_cached(user_id: Any) -> Any:
    """Fetch a user by ID, honouring a 30 s in-process TTL cache."""
    now = time.monotonic()
    lock = _get_user_cache_lock()

    async with lock:
        entry = _USER_CACHE.get(user_id)
        if entry is not None:
            user, expires_at = entry
            if now < expires_at:
                return user
            del _USER_CACHE[user_id]

    user = await get_user_by_id(user_id)

    async with lock:
        if len(_USER_CACHE) >= _USER_CACHE_MAXSIZE:
            evict_now = time.monotonic()
            batch = max(1, int(_USER_CACHE_MAXSIZE * 0.1))
            stale = [k for k, (_, exp) in _USER_CACHE.items() if exp < evict_now][:batch]
            if not stale:
                stale = list(_USER_CACHE.keys())[:batch]
            for k in stale:
                del _USER_CACHE[k]
        _USER_CACHE[user_id] = (user, time.monotonic() + _USER_CACHE_TTL)

    return user


# ---------------------------------------------------------------------------
# Base Class
# ---------------------------------------------------------------------------


class BaseAuthentication(ABC):
    """Base class for all authentication schemes."""

    @abstractmethod
    async def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        """
        Authenticate the request and return a two-tuple of (user, auth_info).
        Return None if authentication is not performed.
        """
        pass

    def authenticate_header(self, request: Request) -> str | None:
        """
        Return a string to be used as the value of the WWW-Authenticate
        header in a 401 response.
        """
        return None


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


class JWTAuthentication(BaseAuthentication):
    """Token based authentication using JSON Web Tokens."""

    async def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        auth_header: str | None = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        try:
            payload = decode_access_token(token)
            jti = payload.get("jti")
            if jti and await is_token_revoked(jti):
                return None

            user_id = payload.get("sub")
            if user_id:
                user = await get_user_cached(user_id)
                if user and user.is_active:
                    return user, {"type": "jwt", "token": token}
        except TokenExpired:
            logger.debug("JWT token expired for request to %s", request.path)
        except Exception as exc:
            logger.warning("JWT authentication error: %s", exc)

        return None

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class SessionAuthentication(BaseAuthentication):
    """Use Django-style sessions for authentication."""

    async def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        """Authenticate using the session attached by SessionMiddleware.

        Fast path: if SessionMiddleware already loaded an authenticated user
        into ``scope["user"]``, return it immediately without a DB query.
        Fallback: resolve the user from the session store, loading from cookie
        if SessionMiddleware is not in the middleware stack.
        """
        scope_user = getattr(request, "_scope", {}).get("user")
        if (
            scope_user is not None
            and getattr(scope_user, "is_authenticated", False)
            and getattr(scope_user, "is_active", True)
        ):
            return scope_user, {"type": "session"}

        session = request.session
        session_key = session.key if session and not session.is_empty else None

        # If no session was populated by SessionMiddleware, try loading
        # directly from the cookie so SessionAuthentication works standalone.
        if not session_key:
            cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
            session_key = request.cookies.get(cookie_name)

        if not session_key:
            return None

        try:
            store = get_session_store()

            user = await store.get_user(session_key)
            if user and getattr(user, "is_active", True):
                return user, {"type": "session"}
        except Exception as exc:
            logger.warning("Session authentication error: %s", exc)

        return None
