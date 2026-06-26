"""Per-dialect database support with lifecycle persistence.

Each supported dialect ships its own module (``sqlite.py``,
``postgres.py``, ``mariadb.py``, ``mssql.py``, ``oracle.py``) bundling
*all* database-specific functionality into a single :class:`Dialect`
subclass:

- Schema introspection (querying column names, autoincrement, unique)
- EXPLAIN statement syntax
- Engine configuration (connect args, pragmas, JSON serializers)
- Identifier quoting and SQL literal formatting
- URL normalization and vendor extraction
- Driver availability checking (lazy importlib probe)

The configured dialect is resolved from the ``DATABASE_URL`` in
``DATABASES`` at startup via :func:`resolve_dialect` and cached for the
process lifecycle via :func:`get_dialect`.  Only the configured
dialect's driver is ever checked for availability - unused dialect
modules never trigger an import.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from openviper.conf import settings
from openviper.db.dialects.base import Dialect
from openviper.db.dialects.mariadb import MariaDBDialect
from openviper.db.dialects.mssql import MSSQLDialect
from openviper.db.dialects.oracle import OracleDialect
from openviper.db.dialects.postgres import PostgreSQLDialect
from openviper.db.dialects.sqlite import SQLiteDialect
from openviper.db.utils import get_default_database_url

logger = logging.getLogger(__name__)

try:
    from sqlalchemy.dialects.oracle.oracledb import (
        OracleDialectAsync_oracledb as _OracleAsyncDialect,
    )

    _oracle_async_available: bool = True
except ImportError:
    _oracle_async_available = False


def patch_oracle_json_serializers() -> None:
    """Patch the oracledb async dialect with JSON serializer defaults.

    The oracledb async dialect does not provide ``_json_deserializer``
    by default.  If ``configure_engine`` is not called (e.g. when an
    engine is created outside OpenViper's connection management), this
    ensures the attribute exists so ``sa.JSON`` result processing does
    not raise ``AttributeError``.

    Uses ``staticmethod`` wrapper to prevent Python from binding
    ``json.dumps``/``json.loads`` as instance methods, which would
    cause a ``TypeError`` when SQLAlchemy calls them with a single
    argument.
    """
    if not _oracle_async_available:
        return
    if not hasattr(_OracleAsyncDialect, "_json_deserializer"):
        _OracleAsyncDialect._json_deserializer = staticmethod(json.loads)
    if not hasattr(_OracleAsyncDialect, "_json_serializer"):
        _OracleAsyncDialect._json_serializer = staticmethod(json.dumps)


patch_oracle_json_serializers()

__all__ = [
    "Dialect",
    "MariaDBDialect",
    "MSSQLDialect",
    "OracleDialect",
    "PostgreSQLDialect",
    "SQLiteDialect",
    "resolve_dialect",
    "resolve_dialect_by_vendor",
    "get_dialect",
    "reset_dialect",
]

_DIALECT_CLASSES: dict[str, type[Dialect]] = {
    "sqlite": SQLiteDialect,
    "postgresql": PostgreSQLDialect,
    "mysql": MariaDBDialect,
    "mssql": MSSQLDialect,
    "oracle": OracleDialect,
}

_resolved_dialect: Dialect | None = None


def resolve_dialect(url: str) -> Dialect:
    """Resolve and cache the :class:`Dialect` for the given database URL.

    The vendor is extracted from the URL scheme, mapped to a dialect
    class, instantiated, and cached for the process lifecycle.  On
    subsequent calls the cached instance is returned unless
    :func:`reset_dialect` is called.

    If the dialect's async driver is not installed,
    :meth:`Dialect.is_driver_available` returns ``False`` but no
    exception is raised - the caller (engine creation) will surface a
    clear ``ModuleNotFoundError`` with install instructions.

    Unknown vendors fall back to the generic :class:`Dialect` base.
    """
    global _resolved_dialect

    if _resolved_dialect is not None:
        return _resolved_dialect

    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0]

    vendor_map = {
        "postgresql": "postgresql",
        "postgres": "postgresql",
        "mysql": "mysql",
        "mariadb": "mysql",
        "sqlite": "sqlite",
        "oracle": "oracle",
        "mssql": "mssql",
    }
    vendor = vendor_map.get(scheme, scheme)

    dialect_cls = _DIALECT_CLASSES.get(vendor, Dialect)
    _resolved_dialect = dialect_cls()

    if not _resolved_dialect.is_driver_available():
        logger.warning(
            "Database driver for dialect '%s' is not installed"
            " (module '%s'). Install it to use this database.",
            vendor,
            _resolved_dialect.driver_module or "unknown",
        )

    logger.debug("Resolved dialect '%s' from URL scheme '%s'.", vendor, scheme)
    return _resolved_dialect


def resolve_dialect_by_vendor(vendor: str) -> Dialect:
    """Return a :class:`Dialect` instance for *vendor* without caching.

    Used when the dialect must be resolved from a live connection's
    drivername rather than the DATABASES config.  Does not check
    driver availability since the connection is already established.
    """
    dialect_cls = _DIALECT_CLASSES.get(vendor, Dialect)
    return dialect_cls()


def get_dialect() -> Dialect:
    """Return the currently resolved dialect.

    If :func:`resolve_dialect` has not been called yet, resolves from
    the default database URL in settings.
    """
    if _resolved_dialect is not None:
        return _resolved_dialect

    url = getattr(settings, "DATABASE_URL", "")
    if not url:
        databases = getattr(settings, "DATABASES", {})
        if databases:
            default = databases.get("default", {})
            if isinstance(default, dict):
                url = default.get("URL", "")

    if not url:
        url = "sqlite:///:memory:"

    return resolve_dialect(url)


def reset_dialect() -> None:
    """Clear the cached dialect.  Useful for tests that change DATABASE_URL."""
    global _resolved_dialect
    _resolved_dialect = None
