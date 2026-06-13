"""Low-level session utilities for OpenViper."""

from __future__ import annotations

import asyncio
import datetime
import secrets
from dataclasses import dataclass

import sqlalchemy as sa

from openviper.auth.cache_utils import ensure_table
from openviper.conf import settings
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


@dataclass
class SessionCookieConfig:
    """Session cookie configuration read from settings."""

    cookie_name: str
    httponly: bool
    samesite: str
    secure: bool
    path: str
    domain: str | None
    max_age: int


def get_session_cookie_config() -> SessionCookieConfig:
    """Read session cookie settings from the application configuration.

    Returns a SessionCookieConfig with all cookie parameters resolved,
    including max_age computed from SESSION_TIMEOUT (which may be a
    timedelta or an integer number of seconds).
    """
    cookie_name: str = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
    httponly: bool = getattr(settings, "SESSION_COOKIE_HTTPONLY", True)
    samesite: str = getattr(settings, "SESSION_COOKIE_SAMESITE", "lax")
    secure: bool = getattr(settings, "SESSION_COOKIE_SECURE", True)
    path: str = getattr(settings, "SESSION_COOKIE_PATH", "/")
    domain: str | None = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
    timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
    if isinstance(timeout, datetime.timedelta):
        max_age = int(timeout.total_seconds())
    else:
        max_age = int(timeout)

    return SessionCookieConfig(
        cookie_name=cookie_name,
        httponly=httponly,
        samesite=samesite,
        secure=secure,
        path=path,
        domain=domain,
        max_age=max_age,
    )
