"""Oracle Database dialect support.

Bundles all Oracle-specific functionality: schema introspection,
EXPLAIN, engine configuration, identifier quoting, URL normalization,
and driver availability checking for ``oracledb``.
"""

from __future__ import annotations

import json
import logging
import typing as t

from openviper.db.dialects.base import Dialect

logger = logging.getLogger("openviper.dialects.oracle")


class OracleDialect(Dialect):
    """Unified Oracle Database dialect support."""

    dialect = "oracle"
    driver_module = "oracledb"

    url_replacements = {
        "oracle://": "oracle+oracledb_async://",
    }

    def _vendor_map(self) -> dict[str, str]:
        return {"oracle": "oracle"}

    # ── Identifier quoting ────────────────────────────────────────────

    def quote_identifier(self, name: str) -> str:
        return name.upper()

    def sql_literal(self, value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    # ── Schema introspection ──────────────────────────────────────────

    def get_real_columns_sql(
        self, table_name: str
    ) -> tuple[str, dict[str, object] | None]:
        return (
            "SELECT column_name FROM all_tab_columns"
            " WHERE owner = USER AND table_name = UPPER(:tname)",
            {"tname": table_name},
        )

    # ── EXPLAIN ───────────────────────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        return [f"EXPLAIN PLAN FOR {compiled_sql}"]

    # ── Engine configuration ──────────────────────────────────────────

    def configure_engine(self, engine: t.Any, async_url: str) -> None:
        """Set JSON serializer/deserializer on the engine's dialect.

        Oracle's oracledb dialect does not provide ``_json_deserializer``
        by default, which causes ``AttributeError`` when SQLAlchemy's
        ``JSON`` type processes result columns.  Setting both
        ``_json_deserializer`` and ``_json_serializer`` on the dialect
        object ensures correct JSON column handling.
        """
        if "oracle" in async_url:
            engine.dialect._json_deserializer = json.loads
            engine.dialect._json_serializer = json.dumps
