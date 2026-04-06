"""Filename generation utilities for database backup archives."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

_SAFE_DBNAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_db_name(name: str) -> str:
    """Return *name* with unsafe characters replaced by underscores.

    Only alphanumeric characters and underscores are kept so the result
    is always safe to embed in a filesystem path.
    """
    sanitized = _SAFE_DBNAME_RE.sub("_", name)
    return re.sub(r"_+", "_", sanitized).strip("_") or "database"


def generate_backup_filename(db_name: str, *, compress: bool = True) -> str:
    """Generate a UTC datetime-stamped backup filename.

    Args:
        db_name: The logical database name (e.g. ``"postgres"`` or ``"mydb"``).
        compress: When ``True`` the filename ends with ``.tar.gz``; otherwise
            ``.sql``.

    Returns:
        A filename in the form ``{db_name}_{YYYYMMDD-HHMMSS}.tar.gz`` (or
        ``.sql`` when *compress* is ``False``).
    """
    safe_name = sanitize_db_name(db_name)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    extension = ".tar.gz" if compress else ".sql"
    return f"{safe_name}_{stamp}{extension}"


def parse_db_name_from_url(database_url: str) -> str:
    """Extract a short logical database name from a SQLAlchemy-style URL.

    For SQLite this returns the stem of the database file.  For all other
    databases it returns the path component after the last ``/``.

    Args:
        database_url: A database URL such as
            ``"postgresql+asyncpg://user:pass@host/mydb"``.

    Returns:
        A short, sanitise-ready name string.
    """
    clean_url = database_url.split("?")[0]
    parsed = urlparse(clean_url)

    db_path = parsed.path.strip("/")

    if not db_path:
        return "database"

    basename = db_path.rsplit("/", 1)[-1]

    stem, dot, ext = basename.rpartition(".")
    if dot and ext.lower() in {"db", "sqlite3", "sqlite"}:
        return stem or "database"

    return basename or "database"
