"""Session management for OpenViper.

Sessions are stored in the database (openviper_sessions table).
The session ID is a cryptographically random token stored in a cookie.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import secrets
import time
from http.cookies import SimpleCookie
from typing import Any, Final

import sqlalchemy as sa

from openviper.auth.user import get_user_by_id
from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

_SESSION_TABLE: sa.Table | None = None

# ---------------------------------------------------------------------------
# Session cache: Avoid DB queries on every request
# ---------------------------------------------------------------------------
_SESSION_CACHE: dict[str, tuple[Any, float]] = {}
_SESSION_CACHE_LOCK: asyncio.Lock | None = None
_SESSION_CACHE_TTL: Final[float] = 60.0  # 60s balances cache hit-rate with invalidation latency
_SESSION_CACHE_MAXSIZE: Final[int] = 4096


def _get_session_cache_lock() -> asyncio.Lock:
    """Return the module-level session cache lock, creating it if necessary."""
    global _SESSION_CACHE_LOCK
    if _SESSION_CACHE_LOCK is None:
        _SESSION_CACHE_LOCK = asyncio.Lock()
    return _SESSION_CACHE_LOCK


def _get_session_table() -> sa.Table:
    global _SESSION_TABLE
    if _SESSION_TABLE is None:
        meta = get_metadata()
        _SESSION_TABLE = sa.Table(
            "openviper_sessions",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_key", sa.String(64), unique=True, nullable=False),
            sa.Column("user_id", sa.String(64), nullable=True),
            sa.Column("data", sa.Text, nullable=False, default="{}"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), default=timezone.now),
        )
    return _SESSION_TABLE


async def _ensure_table() -> None:
    table = _get_session_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(table.metadata.create_all)


def generate_session_key() -> str:
    return secrets.token_urlsafe(48)


def _is_valid_session_key(key: str) -> bool:
    """Validate session key format.

    Session keys should be URL-safe base64 strings with reasonable length.
    Increased minimum length from 4 to 32 characters.
    """
    if not key or not isinstance(key, str):
        return False
    if len(key) > 128 or len(key) < 32:  # Minimum 32 chars for strength
        return False
    # Allow alphanumeric, underscore, hyphen (URL-safe base64 chars)
    return all(c.isalnum() or c in ("-", "_") for c in key)


async def create_session(user_id: int, data: dict[str, Any] | None = None) -> str:
    """Create a new session for the given user.

    Args:
        user_id: The authenticated user's primary key.
        data: Optional extra data to store in the session.

    Returns:
        The session key (store in a cookie).
    """
    await _ensure_table()
    table = _get_session_table()

    key = generate_session_key()
    timeout = getattr(settings, "SESSION_TIMEOUT", None)
    if timeout is None:
        timeout = datetime.timedelta(hours=1)
    expires = timezone.now() + timeout
    payload = json.dumps(data or {})

    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(table).values(
                session_key=key,
                user_id=user_id,
                data=payload,
                expires_at=expires,
                created_at=timezone.now(),
            )
        )
    return key


async def get_user_from_session(cookie_header: str) -> Any | None:
    """Parse the cookie header and look up the user from the session store.

    Uses a 30-second TTL cache to avoid DB queries on every request.

    Args:
        cookie_header: Raw ``Cookie`` header value.

    Returns:
        User instance or None.
    """
    try:
        cookie_name = settings.SESSION_COOKIE_NAME
    except AttributeError:
        cookie_name = "sessionid"

    # Use stdlib SimpleCookie for efficient, standards-compliant parsing
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    session_key = cookie.get(cookie_name)
    if not session_key:
        return None

    # Extract the value from the Morsel object
    session_key_value = session_key.value

    # Validate session key format (should be URL-safe base64, max 64 chars)
    if not _is_valid_session_key(session_key_value):
        return None

    # ── Fast path: check cache first ────────────────────────────────────
    now = time.monotonic()
    lock = _get_session_cache_lock()

    async with lock:
        entry = _SESSION_CACHE.get(session_key_value)
        if entry is not None:
            user, expires_at = entry
            if now < expires_at:
                return user
            # Expired; remove from cache
            del _SESSION_CACHE[session_key_value]

    # ── Slow path: DB lookup (no lock held) ─────────────────────────────
    await _ensure_table()
    table = _get_session_table()
    engine = await get_engine()

    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(table).where(
                sa.and_(
                    table.c.session_key == session_key_value,
                    table.c.expires_at > timezone.now(),
                )
            )
        )
        row = result.fetchone()

    if row is None:
        return None

    user_id = row.user_id
    if user_id is None:
        return None

    user = await get_user_by_id(user_id)

    # ── Cache the result ────────────────────────────────────────────────
    if user is not None:
        async with lock:
            # Evict old entries if cache is full
            if len(_SESSION_CACHE) >= _SESSION_CACHE_MAXSIZE:
                evict_now = time.monotonic()
                batch = max(1, int(_SESSION_CACHE_MAXSIZE * 0.1))
                stale = [k for k, (_, exp) in _SESSION_CACHE.items() if exp < evict_now][:batch]
                if not stale:  # No expired entries; evict oldest
                    stale = list(_SESSION_CACHE.keys())[:batch]
                for k in stale:
                    del _SESSION_CACHE[k]

            _SESSION_CACHE[session_key_value] = (user, now + _SESSION_CACHE_TTL)

    return user


async def delete_session(session_key: str) -> None:
    """Invalidate a session (logout) and prune expired sessions."""
    await _ensure_table()
    table = _get_session_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.delete(table).where(table.c.session_key == session_key))
        # Opportunistically clean up any expired sessions at the same time.
        await conn.execute(sa.delete(table).where(table.c.expires_at <= timezone.now()))

    # Invalidate cache entry
    lock = _get_session_cache_lock()
    async with lock:
        _SESSION_CACHE.pop(session_key, None)


def clear_session_cache() -> None:
    """Clear the entire session cache. Useful for testing or forced refresh."""
    _SESSION_CACHE.clear()
