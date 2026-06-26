"""Microsoft SQL Server dialect support.

Bundles all MSSQL-specific functionality: schema introspection,
DDL generation, EXPLAIN, engine configuration, identifier quoting,
URL normalization, and driver availability checking for ``aioodbc``.
"""

from __future__ import annotations

import logging

from openviper.db.dialects.base import Dialect

logger = logging.getLogger("openviper.migrations")


class MSSQLDialect(Dialect):
    """Unified Microsoft SQL Server dialect support."""

    dialect = "mssql"
    driver_module = "aioodbc"

    url_replacements = {
        "mssql://": "mssql+aioodbc://",
    }

    def _vendor_map(self) -> dict[str, str]:
        return {"mssql": "mssql"}

    # ── Identifier quoting ────────────────────────────────────────────

    def quote_identifier(self, name: str) -> str:
        return f"[{name.replace(']', ']]')}]"

    def sql_literal(self, value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    # ── Schema introspection ──────────────────────────────────────────

    def get_real_columns_sql(
        self, table_name: str
    ) -> tuple[str, dict[str, object] | None]:
        return (
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_catalog = DB_NAME() AND table_name = :tname",
            {"tname": table_name},
        )

    # ── EXPLAIN ───────────────────────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        return [f"SET SHOWPLAN_TEXT ON; {compiled_sql}"]
