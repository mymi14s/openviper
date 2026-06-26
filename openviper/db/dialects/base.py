"""Base class for per-dialect database support.

Each concrete dialect (``sqlite.py``, ``postgres.py``, ``mssql.py``,
``mariadb.py``, ``oracle.py``) subclasses :class:`Dialect`` and
overrides the methods that differ from the generic SQL standard.

A dialect instance bundles *all* database-specific behaviour into a
single object so that once the dialect is resolved from the
``DATABASES`` config at startup, the same instance is used throughout
the process lifecycle for introspection, DDL generation, EXPLAIN,
engine configuration, identifier quoting, SQL literals, and URL
normalization.

Driver availability is checked lazily via :meth:`is_driver_available`
so that only the configured dialect's driver is ever imported.
"""

from __future__ import annotations

import importlib.util
import typing as t
from urllib.parse import urlparse


class Dialect:
    """Unified per-dialect database support.

    Subclasses override the attributes and methods that differ for
    their dialect.  All methods are pure functions of their arguments;
    they never read global state, which keeps them deterministic and
    testable.
    """

    dialect: str = "generic"

    # ── Driver availability ───────────────────────────────────────────

    driver_module: str = ""
    """Importable module name for the async driver (empty for generic)."""

    fallback_driver_module: str = ""
    """Secondary driver to check when *driver_module* is absent."""

    def is_driver_available(self) -> bool:
        """Return whether this dialect's async driver is installed.

        Only the configured dialect ever calls this, so unused dialect
        files never trigger an import.
        """
        for mod in (self.driver_module, self.fallback_driver_module):
            if mod and importlib.util.find_spec(mod) is not None:
                return True
        return not self.driver_module

    # ── URL normalization ─────────────────────────────────────────────

    url_replacements: dict[str, str] = {}
    """Map of sync URL prefixes to async equivalents."""

    def normalize_url(self, url: str) -> str:
        """Translate a sync database URL to its async driver equivalent."""
        for old, new in self.url_replacements.items():
            if url.startswith(old):
                return new + url[len(old):]
        return url

    def extract_vendor(self, url: str) -> str:
        """Return the vendor name derived from *url*."""
        parsed = urlparse(url)
        scheme = parsed.scheme.split("+")[0]
        return self._vendor_map().get(scheme, scheme)

    def _vendor_map(self) -> dict[str, str]:
        return {}

    # ── Identifier quoting and SQL literals ──────────────────────────

    def quote_identifier(self, name: str) -> str:
        """Quote a table or column name for this dialect."""
        return f'"{name.replace(chr(34), chr(34) + chr(34))}"'

    def sql_literal(self, value: object) -> str:
        """Format a Python value as a SQL literal for this dialect."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    # ── Schema introspection ──────────────────────────────────────────

    def get_real_columns_sql(
        self, table_name: str
    ) -> tuple[str, dict[str, object] | None]:
        """Return ``(sql, params)`` for fetching column names of *table_name*."""
        return ("", None)

    def detect_autoincrement(
        self, col_name: str, col_type_str: str, col: dict[str, t.Any]
    ) -> bool:
        """Return whether *col* is an auto-incrementing primary key."""
        if col.get("autoincrement") is not None:
            return bool(col.get("autoincrement"))
        return col.get("identity") is not None

    def detect_unique_columns(
        self, sync_conn: t.Any, table_name: str
    ) -> frozenset[str]:
        """Return column names with a single-column UNIQUE constraint."""
        return frozenset()

    # ── Internal SQL operations ──────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        """Return EXPLAIN output lines for *compiled_sql*."""
        return [f"EXPLAIN {compiled_sql}"]

    # ── Engine configuration ──────────────────────────────────────────

    def get_connect_args(self) -> dict[str, object]:
        """Return dialect-specific ``connect_args`` for engine creation."""
        return {}

    def get_engine_kwargs(
        self, async_url: str, is_memory: bool
    ) -> dict[str, object]:
        """Return dialect-specific kwargs for ``create_async_engine``."""
        return {}

    def configure_engine(self, engine: t.Any, async_url: str) -> None:
        """Apply dialect-specific settings to *engine* after creation."""
