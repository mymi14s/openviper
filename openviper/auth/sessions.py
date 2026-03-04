"""Session management for OpenViper.

Sessions are stored in the database (openviper_sessions table).
The session ID is a cryptographically random token stored in a cookie.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import sqlalchemy as sa

from openviper.auth.backends import get_user_by_id
from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

_SESSION_TABLE: sa.Table | None = None


def _get_session_table() -> sa.Table:
    global _SESSION_TABLE
    if _SESSION_TABLE is None:
        meta = get_metadata()
        _SESSION_TABLE = sa.Table(
            "openviper_sessions",
            meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("session_key", sa.String(64), unique=True, nullable=False),
            sa.Column("user_id", sa.Integer, nullable=True),
            sa.Column("data", sa.Text, nullable=False, default="{}"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), default=lambda: timezone.now()),
        )
    return _SESSION_TABLE


async def _ensure_table() -> None:
    table = _get_session_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(table.metadata.create_all)


def generate_session_key() -> str:
    return secrets.token_urlsafe(48)


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
        import datetime

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

    Args:
        cookie_header: Raw ``Cookie`` header value.

    Returns:
        User instance or None.
    """
    try:
        cookie_name = settings.SESSION_COOKIE_NAME
    except Exception:
        cookie_name = "sessionid"

    session_key = None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{cookie_name}="):
            session_key = part[len(cookie_name) + 1 :]
            break

    if not session_key:
        return None

    await _ensure_table()
    table = _get_session_table()
    engine = await get_engine()

    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(table).where(
                sa.and_(
                    table.c.session_key == session_key,
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

    # Load the user

    return await get_user_by_id(user_id)


async def delete_session(session_key: str) -> None:
    """Invalidate a session (logout) and prune expired sessions."""
    await _ensure_table()
    table = _get_session_table()
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.delete(table).where(table.c.session_key == session_key))
        # Opportunistically clean up any expired sessions at the same time.
        await conn.execute(sa.delete(table).where(table.c.expires_at <= timezone.now()))
