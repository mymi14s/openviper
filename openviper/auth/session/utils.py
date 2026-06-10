"""Low-level session utilities for OpenViper."""

from __future__ import annotations

import asyncio
import secrets

import sqlalchemy as sa

from openviper.auth.cache_utils import ensure_table
from openviper.db.connection import get_metadata
from openviper.utils import timezone

SESSION_TABLE_REF: list[sa.Table | None] = [None]
_SESSION_ENSURED: list[bool] = [False]
TABLE_ENSURE_LOCK = asyncio.Lock()


def generate_session_key() -> str:
    """Generate a cryptographically random URL-safe token."""
    return secrets.token_urlsafe(48)


def is_valid_session_key(key: str | None) -> bool:
    """Validate session key format.

    Rejects keys containing CR/LF characters to prevent HTTP header injection.
    """
    if not key or not isinstance(key, str):
        return False
    if len(key) > 128 or len(key) < 32:
        return False
    if "\r" in key or "\n" in key:
        return False
    return all(c.isalnum() or c in ("-", "_") for c in key)


def get_session_table() -> sa.Table:
    """Return the SQLAlchemy Table for sessions."""
    if SESSION_TABLE_REF[0] is None:
        meta = get_metadata()
        SESSION_TABLE_REF[0] = sa.Table(
            "openviper_sessions",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_key", sa.String(128), unique=True, nullable=False),
            sa.Column("user_id", sa.String(64), nullable=True),
            sa.Column("data", sa.Text, nullable=False, default="{}"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), default=timezone.now),
        )
    table = SESSION_TABLE_REF[0]
    if table is None:
        raise RuntimeError("Session table initialization failed.")
    return table


async def ensure_session_table() -> None:
    """Ensure the session table exists in the database."""
    table = get_session_table()
    await ensure_table(table, _SESSION_ENSURED, TABLE_ENSURE_LOCK)


def reset_session_table_ensured() -> None:
    """Reset the table-ensured flag (for testing only)."""
    _SESSION_ENSURED[0] = False
