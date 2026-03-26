"""Low-level session utilities for OpenViper."""

from __future__ import annotations

import secrets

import sqlalchemy as sa

from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

_SESSION_TABLE: sa.Table | None = None
_TABLE_ENSURED: bool = False


def generate_session_key() -> str:
    """Generate a cryptographically random URL-safe token."""
    return secrets.token_urlsafe(48)


def _is_valid_session_key(key: str) -> bool:
    """Validate session key format."""
    if not key or not isinstance(key, str):
        return False
    if len(key) > 128 or len(key) < 32:
        return False
    return all(c.isalnum() or c in ("-", "_") for c in key)


def _get_session_table() -> sa.Table:
    """Return the SQLAlchemy Table for sessions."""
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
    """Ensure the session table exists in the database.

    Uses a module-level flag so the DDL check runs at most once per
    process lifetime.
    """
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    table = _get_session_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(table.metadata.create_all)
    _TABLE_ENSURED = True


def _reset_table_ensured() -> None:
    """Reset the table-ensured flag (for testing only)."""
    global _TABLE_ENSURED
    _TABLE_ENSURED = False
