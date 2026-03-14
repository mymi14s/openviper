"""Authentication middleware: populates request.user from session or JWT."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Final

from openviper.auth.backends import get_user_by_id
from openviper.auth.jwt import decode_access_token
from openviper.auth.models import AnonymousUser
from openviper.auth.sessions import get_user_from_session
from openviper.auth.token_blocklist import is_token_revoked
from openviper.core.context import current_user as context_current_user
from openviper.exceptions import TokenExpired
from openviper.middleware.base import ASGIApp, BaseMiddleware

logger = logging.getLogger("openviper.auth")

# ---------------------------------------------------------------------------
# Module-level TTL user cache
# ---------------------------------------------------------------------------

_USER_CACHE: dict[int, tuple[Any, float]] = {}
_USER_CACHE_LOCK: Any = None  # asyncio.Lock, created lazily (event-loop-aware)
_USER_CACHE_TTL: Final[float] = 30.0
_USER_CACHE_MAXSIZE: Final[int] = 4096
_LOCK_INIT_GUARD = threading.Lock()


def _get_user_cache_lock() -> Any:
    """Return the module-level cache lock, creating it if necessary.

    Uses a threading lock to prevent a TOCTOU race where two coroutines
    could both see ``_USER_CACHE_LOCK is None`` and create separate locks.
    """
    global _USER_CACHE_LOCK
    if _USER_CACHE_LOCK is None:
        with _LOCK_INIT_GUARD:
            if _USER_CACHE_LOCK is None:
                _USER_CACHE_LOCK = asyncio.Lock()
    return _USER_CACHE_LOCK


async def _get_user_cached(user_id: Any) -> Any:
    """Fetch a user by ID, honouring a 30 s in-process TTL cache.

    Two-phase locking: check cache under lock (fast path), release, fetch
    from DB, re-acquire to store.  This keeps the lock released during the
    potentially slow DB round-trip.
    """
    now = time.monotonic()
    lock = _get_user_cache_lock()

    # ── Fast path: cache hit ─────────────────────────────────────────────
    async with lock:
        entry = _USER_CACHE.get(user_id)
        if entry is not None:
            user, expires_at = entry
            if now < expires_at:
                return user
            del _USER_CACHE[user_id]

    # ── Slow path: DB round-trip (no lock held) ──────────────────────────
    user = await get_user_by_id(user_id)

    # ── Store in cache ────────────────────────────────────────────────────
    async with lock:
        if len(_USER_CACHE) >= _USER_CACHE_MAXSIZE:
            # Lazy eviction: remove up to 10 % of entries, preferring expired
            evict_now = time.monotonic()
            batch = max(1, int(_USER_CACHE_MAXSIZE * 0.1))
            stale = [k for k, (_, exp) in _USER_CACHE.items() if exp < evict_now][:batch]
            if not stale:  # no expired entries; evict oldest by insertion order
                stale = list(_USER_CACHE.keys())[:batch]
            for k in stale:
                del _USER_CACHE[k]
        _USER_CACHE[user_id] = (user, time.monotonic() + _USER_CACHE_TTL)

    return user


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthenticationMiddleware(BaseMiddleware):
    """Identify the authenticated user from session cookie or Authorization header.

    Sets ``scope["user"]`` and ``scope["auth"]`` for downstream handlers.
    If no credentials are present, sets an anonymous user.

    Args:
        app: Next ASGI app.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)  # pylint: disable=useless-parent-delegation
        # Explicit __init__ defined for type-checker clarity; delegates to base

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        user, auth_info = await self._authenticate(scope)
        scope["user"] = user
        scope["auth"] = auth_info

        token = context_current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            context_current_user.reset(token)

    async def _authenticate(self, scope: dict[str, Any]) -> tuple[Any, Any]:
        """Try session then JWT authentication.

        Returns:
            ``(user, auth_info)`` tuple.  ``user`` is :class:`AnonymousUser`
            if not authenticated.
        """
        # Fast header extraction: only extract the 2 headers we need
        # instead of creating a full dict. ~2x faster for large header lists.
        auth_header = b""
        cookie_header = b""
        headers = scope.get("headers", [])

        for name, value in headers:
            if name == b"authorization":
                auth_header = value
            elif name == b"cookie":
                cookie_header = value
            # Early exit if we found both headers
            if auth_header and cookie_header:
                break

        # 1. Try JWT Bearer token
        auth_str = auth_header.decode("latin-1") if auth_header else ""
        if auth_str.startswith("Bearer "):
            token = auth_str[7:]
            try:
                payload = decode_access_token(token)
                jti = payload.get("jti")
                if jti and await is_token_revoked(jti):
                    pass  # token has been revoked — fall through to anonymous
                else:
                    user_id = payload.get("sub")
                    if user_id:
                        user = await _get_user_cached(user_id)
                        if user and user.is_active:
                            return user, {"type": "jwt", "token": token}
            except TokenExpired:
                logger.debug("JWT token expired for request to %s", scope.get("path"))
            except Exception as exc:
                logger.warning("JWT authentication error: %s", exc)

        # 2. Try session cookie
        cookie_str = cookie_header.decode("latin-1") if cookie_header else ""
        if cookie_str:
            try:
                session_user = await get_user_from_session(cookie_str)
                if session_user and getattr(session_user, "is_active", True):
                    return session_user, {"type": "session"}
            except Exception as exc:
                logger.warning("Session authentication error: %s", exc)

        return AnonymousUser(), {"type": "none"}
