"""SQLite dialect support.

Bundles all SQLite-specific functionality: schema introspection,
DDL generation, EXPLAIN, engine configuration, identifier quoting,
URL normalization, and driver availability checking for ``aiosqlite``.
"""

from __future__ import annotations

import logging
import re
import typing as t

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from openviper.db.constants import SAFE_TABLE_NAME_RE
from openviper.db.dialects.base import Dialect

logger = logging.getLogger("openviper.migrations")


class SQLiteDialect(Dialect):
    """Unified SQLite dialect support."""

    dialect = "sqlite"
    driver_module = "aiosqlite"

    url_replacements = {
        "sqlite:///": "sqlite+aiosqlite:///",
        "sqlite://": "sqlite+aiosqlite://",
    }

    def _vendor_map(self) -> dict[str, str]:
        return {"sqlite": "sqlite"}

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
        if not SAFE_TABLE_NAME_RE.match(table_name):
            raise ValueError(f"Unsafe table name for PRAGMA: {table_name!r}")
        return (f'PRAGMA table_info("{table_name}")', None)

    def detect_autoincrement(
        self, col_name: str, col_type_str: str, col: dict[str, t.Any]
    ) -> bool:
        if col_type_str.upper() == "INTEGER":
            return True
        return super().detect_autoincrement(col_name, col_type_str, col)

    def detect_unique_columns(
        self, sync_conn: t.Any, table_name: str
    ) -> frozenset[str]:
        try:
            result = sync_conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_master"
                    " WHERE type = 'table' AND name = :name"
                ),
                {"name": table_name},
            )
            row = result.fetchone()
            if not row or not row[0]:
                return frozenset()
        except Exception:
            return frozenset()

        ddl = row[0]
        unique_cols: set[str] = set()

        inner_match = re.search(
            r'CREATE\s+TABLE\s+"[^"]+"\s*\((.*)\)\s*$',
            ddl, re.DOTALL | re.IGNORECASE,
        )
        if not inner_match:
            return frozenset()

        inner = inner_match.group(1)
        col_defs = re.split(r',\s*\n\s*(?=")', inner)

        for col_def in col_defs:
            col_def = col_def.strip()
            col_match = re.match(r'"([^"]+)"', col_def)
            if not col_match:
                continue
            col_name = col_match.group(1)
            if re.search(r'\bPRIMARY\s+KEY\b', col_def, re.IGNORECASE):
                continue
            if re.search(r'\bUNIQUE\b', col_def, re.IGNORECASE):
                unique_cols.add(col_name)

        table_unique = re.compile(
            r'UNIQUE\s*\(\s*"([^"]+)"\s*\)', re.IGNORECASE
        )
        for match in table_unique.finditer(inner):
            unique_cols.add(match.group(1))

        return frozenset(unique_cols)

    # ── EXPLAIN ───────────────────────────────────────────────────────

    def explain_sql(self, compiled_sql: str) -> list[str]:
        return [f"EXPLAIN QUERY PLAN {compiled_sql}"]

    # ── Engine configuration ──────────────────────────────────────────

    def get_engine_kwargs(
        self, async_url: str, is_memory: bool
    ) -> dict[str, object]:
        if is_memory:
            return {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        return {}

    def configure_engine(self, engine: t.Any, async_url: str) -> None:
        @sa.event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: object, connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
