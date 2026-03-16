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
import time
from typing import Final

import sqlalchemy as sa

from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

_BLOCKLIST_TABLE: sa.Table | None = None
_TABLE_ENSURED: bool = False

# ---------------------------------------------------------------------------
# Dual cache: positive (revoked) and negative (not revoked)
# ---------------------------------------------------------------------------

# Positive cache: jti -> unix timestamp of token expiry (revoked tokens).
_JTI_REVOKED_CACHE: dict[str, float] = {}

# Negative cache: jti -> unix timestamp when to re-check (not revoked tokens).
# This avoids DB queries for the common case of valid, non-revoked tokens.
_JTI_VALID_CACHE: dict[str, float] = {}

_CACHE_LOCK: asyncio.Lock | None = None
_NEGATIVE_CACHE_TTL: Final[float] = 10.0  # Valid-token cache; revocation visible within 10s
_CACHE_MAXSIZE: Final[int] = 8192


def _get_cache_lock() -> asyncio.Lock:
    """Return the module-level cache lock, creating it if necessary."""
    global _CACHE_LOCK
    if _CACHE_LOCK is None:
        _CACHE_LOCK = asyncio.Lock()
    return _CACHE_LOCK


def _evict_if_full(cache: dict[str, float], now: float) -> None:
    """Evict stale (or oldest) entries when *cache* exceeds ``_CACHE_MAXSIZE``.

    Prefers evicting expired entries; falls back to evicting the oldest
    insertion-order entries when all entries are still fresh.
    Must be called while the cache lock is already held.
    """
    if len(cache) <= _CACHE_MAXSIZE:
        return
    batch = max(1, int(_CACHE_MAXSIZE * 0.1))
    stale = [k for k, exp in cache.items() if exp < now][:batch]
    if not stale:  # no expired entries — evict oldest by insertion order
        stale = list(cache.keys())[:batch]
    for k in stale:
        del cache[k]


def _get_blocklist_table() -> sa.Table:
    global _BLOCKLIST_TABLE
    if _BLOCKLIST_TABLE is None:
        meta = get_metadata()
        _BLOCKLIST_TABLE = sa.Table(
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
    return _BLOCKLIST_TABLE


async def _ensure_table() -> None:
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    table = _get_blocklist_table()
    engine = await get_engine()
    with contextlib.suppress(Exception):  # Table/sequence already exists - this is fine
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
    _TABLE_ENSURED = True


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
    await _ensure_table()
    table = _get_blocklist_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        # Upsert — if the same jti is already revoked, do nothing.
        with contextlib.suppress(Exception):
            await conn.execute(
                sa.insert(table).values(
                    jti=jti,
                    token_type=token_type,
                    user_id=user_id,
                    expires_at=expires_at,
                    revoked_at=timezone.now(),
                )
            )

        # Opportunistically prune fully-expired tokens.
        await conn.execute(sa.delete(table).where(table.c.expires_at <= timezone.now()))

    # Update cache: add to revoked cache and remove from valid cache
    lock = _get_cache_lock()
    now = time.time()
    async with lock:
        _JTI_REVOKED_CACHE[jti] = expires_at.timestamp()
        _JTI_VALID_CACHE.pop(jti, None)
        _evict_if_full(_JTI_REVOKED_CACHE, now)


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
    lock = _get_cache_lock()

    # ── Fast path: check both caches under a single lock acquisition ─────
    async with lock:
        cached_expiry = _JTI_REVOKED_CACHE.get(jti)
        if cached_expiry is not None:
            if now < cached_expiry:
                return True
            # Entry has expired naturally; evict and fall through to DB
            del _JTI_REVOKED_CACHE[jti]
        else:
            cached_valid_until = _JTI_VALID_CACHE.get(jti)
            if cached_valid_until is not None:
                if now < cached_valid_until:
                    return False
                # Re-check TTL elapsed; remove and fall through to DB
                del _JTI_VALID_CACHE[jti]

    # ── Slow path: Query DB (no lock held) ──────────────────────────────
    await _ensure_table()
    table = _get_blocklist_table()
    engine = await get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(table.c.expires_at).where(table.c.jti == jti).limit(1)
        )
        row = result.fetchone()

    # ── Update cache based on result ─────────────────────────────────────
    async with lock:
        if row is not None:
            # Token is revoked — add to positive cache, evict from negative
            expiry = row[0]
            if isinstance(expiry, datetime.datetime):
                _JTI_REVOKED_CACHE[jti] = expiry.timestamp()
            _JTI_VALID_CACHE.pop(jti, None)
            _evict_if_full(_JTI_REVOKED_CACHE, now)
            return True

        # Token is NOT revoked — add to negative cache
        _JTI_VALID_CACHE[jti] = now + _NEGATIVE_CACHE_TTL
        _evict_if_full(_JTI_VALID_CACHE, now)
        return False


def clear_token_cache() -> None:
    """Clear the entire token cache. Useful for testing or forced refresh."""
    _JTI_REVOKED_CACHE.clear()
    _JTI_VALID_CACHE.clear()
