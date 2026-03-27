"""Authentication schemes and opaque-token storage for OpenViper.

Contains all three built-in authentication backends (JWT, Token, Session),
the shared TTL user cache, and the opaque-token lifecycle helpers
(``create_token``, ``revoke_token``, ``clear_token_auth_cache``).

Token values are never stored in plain text.  Only the SHA-256 hex-digest of
each token is persisted; the raw value is returned once by :func:`create_token`
and cannot be recovered afterwards.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Final

import sqlalchemy as sa

from openviper.auth._user_cache import _USER_CACHE
from openviper.auth.jwt import decode_access_token
from openviper.auth.session.store import get_session_store
from openviper.auth.token_blocklist import is_token_revoked
from openviper.auth.user import get_user_by_id
from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.exceptions import TokenExpired
from openviper.utils import timezone

if TYPE_CHECKING:
    from openviper.http.request import Request

logger = logging.getLogger("openviper.auth")

# ---------------------------------------------------------------------------
# Module-level TTL user cache (moved from middleware for reuse)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Opaque-token SA table (lazily initialised once, shareable across coroutines)
# ---------------------------------------------------------------------------

_AUTH_TOKENS_TABLE: sa.Table | None = None
_TABLE_ENSURED: bool = False
_TABLE_ENSURE_LOCK: asyncio.Lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Opaque-token in-process TTL cache
# ---------------------------------------------------------------------------

# hash -> (user_id, cache_expiry_monotonic_seconds)
_TOKEN_CACHE: dict[str, tuple[int, float]] = {}
_TOKEN_CACHE_LOCK: asyncio.Lock | None = None
_TOKEN_CACHE_TTL: Final[float] = 600.0  # 10 minutes
_TOKEN_CACHE_MAXSIZE: Final[int] = 4096
_TOKEN_LOCK_INIT_GUARD: threading.Lock = threading.Lock()


def _get_token_cache_lock() -> asyncio.Lock:
    """Return the module-level token cache lock, creating it lazily."""
    global _TOKEN_CACHE_LOCK
    if _TOKEN_CACHE_LOCK is None:
        with _TOKEN_LOCK_INIT_GUARD:
            if _TOKEN_CACHE_LOCK is None:
                _TOKEN_CACHE_LOCK = asyncio.Lock()
    return _TOKEN_CACHE_LOCK


def _hash_token(raw: str) -> str:
    """Return the SHA-256 hex-digest of *raw*."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _evict_if_full(now: float) -> None:
    """Evict stale then oldest entries when the token cache is at capacity.

    Must be called while holding the token cache lock.
    """
    if len(_TOKEN_CACHE) <= _TOKEN_CACHE_MAXSIZE:
        return
    batch = max(1, int(_TOKEN_CACHE_MAXSIZE * 0.1))
    stale = [k for k, (_, exp) in _TOKEN_CACHE.items() if exp < now][:batch]
    if not stale:
        stale = list(_TOKEN_CACHE.keys())[:batch]
    for k in stale:
        del _TOKEN_CACHE[k]


# ---------------------------------------------------------------------------
# SA helpers
# ---------------------------------------------------------------------------


def _get_table() -> sa.Table:
    """Return the ``auth_tokens`` SA ``Table``, creating it once if needed."""
    global _AUTH_TOKENS_TABLE
    if _AUTH_TOKENS_TABLE is None:
        meta = get_metadata()
        _AUTH_TOKENS_TABLE = sa.Table(
            "auth_tokens",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("expires_at", sa.DateTime, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True),
            extend_existing=True,
        )
    return _AUTH_TOKENS_TABLE


async def _ensure_table() -> None:
    """Create the ``auth_tokens`` table if it does not yet exist.

    Uses a module-level flag to run ``CREATE TABLE IF NOT EXISTS`` at most once
    per process lifetime, avoiding repeated DDL round-trips.
    """
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    async with _TABLE_ENSURE_LOCK:
        if _TABLE_ENSURED:
            return
        table = _get_table()
        engine = await get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(table.metadata.create_all, checkfirst=True)
        _TABLE_ENSURED = True


# ---------------------------------------------------------------------------
# Opaque-token public helpers
# ---------------------------------------------------------------------------


async def create_token(user_id: int, expires_at: Any | None = None) -> tuple[str, dict[str, Any]]:
    """Generate a new opaque auth token for *user_id*.

    The raw token value is returned exactly once and is NOT stored.  Only its
    SHA-256 hash is persisted.  Callers must save the raw value immediately.

    Args:
        user_id: Primary key of the user that owns the token.
        expires_at: Optional :class:`datetime.datetime` (UTC) when the token
            expires.  ``None`` means the token never expires.

    Returns:
        A 2-tuple ``(raw_token, record)`` where *record* is a plain ``dict``
        representation of the created row.
    """
    await _ensure_table()
    raw = secrets.token_hex(20)  # 40-char hex string, cryptographically random
    key_hash = _hash_token(raw)
    now_utc = timezone.now()
    table = _get_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        stmt = (
            sa.insert(table)
            .values(
                key_hash=key_hash,
                user_id=user_id,
                created_at=now_utc,
                expires_at=expires_at,
                is_active=True,
            )
            .returning(
                table.c.id,
                table.c.key_hash,
                table.c.user_id,
                table.c.created_at,
                table.c.expires_at,
                table.c.is_active,
            )
        )
        row = (await conn.execute(stmt)).one()

    record: dict[str, Any] = {
        "id": row.id,
        "key_hash": row.key_hash,
        "user_id": row.user_id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "is_active": row.is_active,
    }
    logger.debug("Created auth token for user_id=%s", user_id)
    return raw, record


async def revoke_token(raw: str) -> None:
    """Revoke the token with the given raw value.

    Marks the row ``is_active = False`` in the database and evicts the
    corresponding entry from the in-process cache so that the revocation
    takes effect immediately within this process.

    Args:
        raw: The original raw token string (not the hash).
    """
    await _ensure_table()
    key_hash = _hash_token(raw)
    table = _get_table()
    engine = await get_engine()

    async with engine.begin() as conn:
        await conn.execute(
            sa.update(table).where(table.c.key_hash == key_hash).values(is_active=False)
        )

    lock = _get_token_cache_lock()
    async with lock:
        _TOKEN_CACHE.pop(key_hash, None)

    logger.debug("Revoked auth token (hash prefix %s\u2026)", key_hash[:8])


def clear_token_auth_cache() -> None:
    """Clear the in-process token cache.  Intended for tests and clean shutdown."""
    _TOKEN_CACHE.clear()


# ---------------------------------------------------------------------------
# TokenAuthentication
# ---------------------------------------------------------------------------


class TokenAuthentication(BaseAuthentication):
    """Authenticate requests carrying an ``Authorization: Token <token>`` header.

    Resolution order:
    1. Parse the ``Authorization`` header; reject anything not starting with
       ``"Token "``.
    2. Hash the raw token and check the in-process TTL cache.
    3. On cache miss, query the ``auth_tokens`` table; validate ``is_active``
       and optional ``expires_at``.
    4. Fetch the associated user via :func:`get_user_cached`.
    5. Populate the cache and return ``(user, {"type": "token", "token": raw})``.
    """

    async def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        auth_header: str | None = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Token "):
            return None

        raw = auth_header[6:]
        if not raw:
            return None

        key_hash = _hash_token(raw)
        now_mono = time.monotonic()

        # Fast path: read user_id from cache, then release the lock before
        # calling get_user_cached to avoid holding the lock during async I/O.
        cached_user_id: int | None = None
        lock = _get_token_cache_lock()
        async with lock:
            cached = _TOKEN_CACHE.get(key_hash)
            if cached is not None:
                uid, cache_expires = cached
                if now_mono < cache_expires:
                    cached_user_id = uid
                else:
                    del _TOKEN_CACHE[key_hash]

        if cached_user_id is not None:
            user = await get_user_cached(cached_user_id)
            if user and getattr(user, "is_active", True):
                return user, {"type": "token", "token": raw}

        # Slow path: DB lookup
        try:
            await _ensure_table()
            table = _get_table()
            engine = await get_engine()

            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        sa.select(
                            table.c.user_id,
                            table.c.is_active,
                            table.c.expires_at,
                        ).where(table.c.key_hash == key_hash)
                    )
                ).one_or_none()

            if row is None:
                logger.debug("Token not found in DB (hash prefix %s\u2026)", key_hash[:8])
                return None

            if not row.is_active:
                logger.debug("Token is inactive (hash prefix %s\u2026)", key_hash[:8])
                return None

            if row.expires_at is not None:
                now_utc = timezone.now()
                exp = row.expires_at
                # Normalise to offset-naive for comparison when zones differ.
                if hasattr(exp, "tzinfo") and exp.tzinfo is None and hasattr(now_utc, "tzinfo"):
                    now_compare = now_utc.replace(tzinfo=None)
                else:
                    now_compare = now_utc
                if now_compare > exp:
                    logger.debug("Token has expired (hash prefix %s\u2026)", key_hash[:8])
                    return None

            user_id: int = row.user_id
            user = await get_user_cached(user_id)
            if not user or not getattr(user, "is_active", True):
                return None

            async with lock:
                _evict_if_full(now_mono)
                _TOKEN_CACHE[key_hash] = (user_id, now_mono + _TOKEN_CACHE_TTL)

            return user, {"type": "token", "token": raw}

        except Exception as exc:
            logger.warning("TokenAuthentication error: %s", exc)
            return None

    def authenticate_header(self, request: Request) -> str:
        return "Token"
