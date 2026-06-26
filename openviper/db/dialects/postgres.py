"""PostgreSQL dialect support.

Bundles all PostgreSQL-specific functionality: schema introspection,
DDL generation, EXPLAIN, engine configuration, identifier quoting,
URL normalization, and driver availability checking for ``asyncpg``.
"""

from __future__ import annotations

from openviper.conf import settings
from openviper.db.dialects.base import Dialect
from openviper.db.utils import validate_pool_config


class PostgreSQLDialect(Dialect):
    """Unified PostgreSQL dialect support."""

    dialect = "postgresql"
    driver_module = "asyncpg"

    url_replacements = {
        "postgresql://": "postgresql+asyncpg://",
        "postgres://": "postgresql+asyncpg://",
    }

    def _vendor_map(self) -> dict[str, str]:
        return {"postgresql": "postgresql", "postgres": "postgresql"}

    # ── Identifier quoting ────────────────────────────────────────────

    def quote_identifier(self, name: str) -> str:
        return f'"{name.replace(chr(34), chr(34) + chr(34))}"'

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
            " WHERE table_name = :tname",
            {"tname": table_name},
        )

    # ── EXPLAIN ───────────────────────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        return [f"EXPLAIN {compiled_sql}"]

    # ── Engine configuration ──────────────────────────────────────────

    def get_engine_kwargs(
        self, async_url: str, is_memory: bool
    ) -> dict[str, object]:
        if "asyncpg" not in async_url:
            return {}

        stmt_cache = validate_pool_config(
            getattr(settings, "PREPARED_STMT_CACHE", 256)
            if hasattr(settings, "PREPARED_STMT_CACHE")
            else 256,
            "PREPARED_STMT_CACHE",
            min_val=0,
            max_val=2048,
            default=256,
        )
        return {"connect_args": {"prepared_statement_cache_size": stmt_cache}}
