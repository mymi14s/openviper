"""MariaDB / MySQL dialect support.

Bundles all MariaDB and MySQL-specific functionality: schema
introspection, DDL generation, EXPLAIN, engine configuration,
identifier quoting, URL normalization, and driver availability
checking for ``aiomysql``.
"""

from __future__ import annotations

from openviper.db.dialects.base import Dialect


class MariaDBDialect(Dialect):
    """Unified MariaDB / MySQL dialect support."""

    dialect = "mysql"
    driver_module = "aiomysql"

    url_replacements = {
        "mysql://": "mysql+aiomysql://",
        "mariadb://": "mysql+aiomysql://",
    }

    def _vendor_map(self) -> dict[str, str]:
        return {"mysql": "mysql", "mariadb": "mysql"}

    # ── Identifier quoting ────────────────────────────────────────────

    def quote_identifier(self, name: str) -> str:
        return f"`{name.replace('`', '``')}`"

    def sql_literal(self, value: object) -> str:
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
        return (
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = DATABASE() AND table_name = :tname",
            {"tname": table_name},
        )

    # ── EXPLAIN ───────────────────────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        return [f"EXPLAIN {compiled_sql}"]

    # ── Engine configuration ──────────────────────────────────────────

    def get_engine_kwargs(
        self, async_url: str, is_memory: bool
    ) -> dict[str, object]:
        if "aiomysql" in async_url:
            return {"pool_pre_ping": False}
        return {}
