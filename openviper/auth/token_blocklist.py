"""Token revocation (blocklist) for OpenViper JWT authentication.

Revoked tokens are stored in the database so that logout is honoured even
before the token's natural expiry.  Both access and refresh tokens carry a
``jti`` (JWT ID) claim that uniquely identifies each issued token; that ID
is stored here on revocation and checked on every decode.

Expired rows are pruned opportunistically during revocation calls to keep
the table from growing unboundedly.
"""

from __future__ import annotations

import datetime
import time

import sqlalchemy as sa

from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

_BLOCKLIST_TABLE: sa.Table | None = None
_TABLE_ENSURED: bool = False

# In-memory cache: jti -> unix timestamp of token expiry.
# Avoids a DB round-trip on every JWT request for non-revoked tokens.
_JTI_CACHE: dict[str, float] = {}


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
            sa.Column("user_id", sa.Integer, nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=False,
                default=lambda: timezone.now(),
            ),
        )
    return _BLOCKLIST_TABLE


async def _ensure_table() -> None:
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    table = _get_blocklist_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
    _TABLE_ENSURED = True


async def revoke_token(
    jti: str,
    token_type: str,
    user_id: int | None,
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
        try:
            await conn.execute(
                sa.insert(table).values(
                    jti=jti,
                    token_type=token_type,
                    user_id=user_id,
                    expires_at=expires_at,
                    revoked_at=timezone.now(),
                )
            )
        except Exception:
            # Duplicate jti (already revoked) — safe to ignore.
            pass

        # Opportunistically prune fully-expired tokens.
        await conn.execute(sa.delete(table).where(table.c.expires_at <= timezone.now()))

    # Populate the in-memory cache so subsequent checks skip the DB.
    _JTI_CACHE[jti] = expires_at.timestamp()


async def is_token_revoked(jti: str) -> bool:
    """Check whether a token has been revoked.

    Args:
        jti: The ``jti`` claim from the token payload.

    Returns:
        ``True`` if the token is in the blocklist, ``False`` otherwise.
    """
    # Fast path: check in-memory cache before hitting the DB.
    cached_expiry = _JTI_CACHE.get(jti)
    if cached_expiry is not None:
        if time.time() < cached_expiry:
            return True
        # The entry has expired; evict and let the DB confirm.
        del _JTI_CACHE[jti]

    await _ensure_table()
    table = _get_blocklist_table()
    engine = await get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(table.c.expires_at).where(table.c.jti == jti).limit(1)
        )
        row = result.fetchone()
        if row is None:
            return False
        # Cache the result for future hot-path checks.
        expiry = row[0]
        if isinstance(expiry, datetime.datetime):
            _JTI_CACHE[jti] = expiry.timestamp()
        return True
