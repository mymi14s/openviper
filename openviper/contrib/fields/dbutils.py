"""Shared database utility functions for contrib field packages."""

from __future__ import annotations

from openviper.conf import settings
from openviper.db import connection as db_connection
from openviper.db.utils import get_default_database_url


def is_postgresql() -> bool:
    """Return True if the configured database engine targets PostgreSQL.

    Checks the live engine URL first, then falls back to settings.
    """
    try:
        engine = db_connection._engine
        if engine is not None:
            url = str(engine.url)
            return "postgresql" in url or "postgres" in url
    except (AttributeError, TypeError):  # fmt: skip
        pass
    try:
        url = get_default_database_url(settings)
        return "postgresql" in url or "postgres" in url
    except (AttributeError, TypeError):  # fmt: skip
        pass
    return False
