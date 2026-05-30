"""Token revocation (blocklist) for OpenViper JWT authentication.

Revoked tokens are stored in the database so that logout is honoured even
before the token's natural expiry.  Both access and refresh tokens carry a
``jti`` (JWT ID) claim that uniquely identifies each issued token; that ID
is stored here on revocation and checked on every decode.

Expired rows are pruned opportunistically during revocation calls to keep
the table from growing unboundedly.

Performance: Uses dual caching strategy:
  - Positive cache: Known revoked tokens (avoids DB query)
  - Negative cache: Known valid tokens (avoids DB query for common case)
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import threading
import time
from typing import Final

import sqlalchemy as sa

from openviper.auth._cache_utils import ensure_table, evict_cache_if_full, lazy_async_lock
from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

BLOCKLIST_TABLE_REF: list[sa.Table | None] = [None]
_TABLE_ENSURED: list[bool] = [False]
TABLE_ENSURE_LOCK: asyncio.Lock = asyncio.Lock()


# Intent: Avoid DB queries for revoked tokens by caching their expiry timestamps.
JTI_REVOKED_CACHE: dict[str, float] = {}

# Intent: Avoid DB queries for valid tokens by caching negative results with a short TTL.
JTI_VALID_CACHE: dict[str, float] = {}

_CACHE_LOCK_REF: list[asyncio.Lock | None] = [None]
_CACHE_LOCK_GUARD: threading.Lock = threading.Lock()
NEGATIVE_CACHE_TTL: Final[float] = 10.0  # Valid-token cache; revocation visible within 10s
CACHE_MAXSIZE: Final[int] = 8192


def get_blocklist_cache_lock() -> asyncio.Lock:
    """Return the module-level cache lock, creating it if necessary."""
    return lazy_async_lock(_CACHE_LOCK_REF, _CACHE_LOCK_GUARD)


def evict_blocklist_cache_if_full(cache: dict[str, float], now: float) -> None:
    """Evict stale (or oldest) entries when *cache* exceeds ``CACHE_MAXSIZE``.

    Prefers evicting expired entries; falls back to evicting the oldest
    insertion-order entries when all entries are still fresh.
    Must be called while the cache lock is already held.
    """
    evict_cache_if_full(cache, CACHE_MAXSIZE, now, lambda v: v)


def get_blocklist_table() -> sa.Table:
    if BLOCKLIST_TABLE_REF[0] is None:
        meta = get_metadata()
        BLOCKLIST_TABLE_REF[0] = sa.Table(
            "openviper_token_blocklist",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("jti", sa.String(64), unique=True, nullable=False, index=True),
            sa.Column("token_type", sa.String(16), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=False,
                default=timezone.now,
            ),
        )
    table = BLOCKLIST_TABLE_REF[0]
    if table is None:
        raise RuntimeError("Token blocklist table initialization failed.")
    return table


async def ensure_blocklist_table() -> None:
    table = get_blocklist_table()
    await ensure_table(
        table,
        _TABLE_ENSURED,
        TABLE_ENSURE_LOCK,
        suppress_errors=(sa.exc.OperationalError, sa.exc.ProgrammingError),
    )


async def revoke_token(
    jti: str,
    token_type: str,
    user_id: str | int | None,
    expires_at: datetime.datetime,
) -> None:
    """Add a token to the blocklist.

    Args:
        jti: The ``jti`` claim from the token payload.
        token_type: ``"access"`` or ``"refresh"``.
        user_id: Owner of the token (used for audit / bulk-revoke queries).
        expires_at: When the token would naturally expire.  Rows older than
            this are safe to prune.
    """
    await ensure_blocklist_table()
    table = get_blocklist_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        # Intent: Treat repeated revocations as idempotent writes.
        with contextlib.suppress(sa.exc.IntegrityError):
            await conn.execute(
                sa.insert(table).values(
                    jti=jti,
                    token_type=token_type,
                    user_id=user_id,
                    expires_at=expires_at,
                    revoked_at=timezone.now(),
                )
            )

        # Intent: Prune expired rows during revoke to keep the table small.
        await conn.execute(sa.delete(table).where(table.c.expires_at <= timezone.now()))

    lock = get_blocklist_cache_lock()
    now = time.time()
    async with lock:
        JTI_REVOKED_CACHE[jti] = expires_at.timestamp()
        JTI_VALID_CACHE.pop(jti, None)
        evict_blocklist_cache_if_full(JTI_REVOKED_CACHE, now)


async def is_token_revoked(jti: str) -> bool:
    """Check whether a token has been revoked.

    Uses a dual-cache strategy:
      1. Check positive cache (known revoked tokens) - return True immediately
      2. Check negative cache (known valid tokens) - return False if still valid
      3. Query DB if not in either cache and update cache accordingly

    Args:
        jti: The ``jti`` claim from the token payload.

    Returns:
        ``True`` if the token is in the blocklist, ``False`` otherwise.
    """
    now = time.time()
    lock = get_blocklist_cache_lock()

    async with lock:
        cached_expiry = JTI_REVOKED_CACHE.get(jti)
        if cached_expiry is not None:
            if now < cached_expiry:
                return True
            del JTI_REVOKED_CACHE[jti]
        else:
            cached_valid_until = JTI_VALID_CACHE.get(jti)
            if cached_valid_until is not None:
                if now < cached_valid_until:
                    return False
                del JTI_VALID_CACHE[jti]

    await ensure_blocklist_table()
    table = get_blocklist_table()
    engine = await get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(table.c.expires_at).where(table.c.jti == jti).limit(1)
        )
        row = result.fetchone()

    async with lock:
        if row is not None:
            # Intent: Keep positive and negative revocation caches exclusive.
            expiry = row[0]
            if isinstance(expiry, datetime.datetime):
                JTI_REVOKED_CACHE[jti] = expiry.timestamp()
            JTI_VALID_CACHE.pop(jti, None)
            evict_blocklist_cache_if_full(JTI_REVOKED_CACHE, now)
            return True

        # Intent: Cache misses to avoid repeated database reads.
        JTI_VALID_CACHE[jti] = now + NEGATIVE_CACHE_TTL
        evict_blocklist_cache_if_full(JTI_VALID_CACHE, now)
        return False


def clear_token_cache() -> None:
    """Clear the entire token cache. Useful for testing or forced refresh."""
    JTI_REVOKED_CACHE.clear()
    JTI_VALID_CACHE.clear()


def is_token_known_revoked(jti: str) -> bool:
    """Return true when *jti* is present in the local revoked-token cache."""
    cached_expiry = JTI_REVOKED_CACHE.get(jti)
    if cached_expiry is None:
        return False
    if time.time() < cached_expiry:
        return True
    JTI_REVOKED_CACHE.pop(jti, None)
    return False
