"""Migration executor and state tracker for OpenViper ORM.

Migrations are plain Python files generated in ``<app>/migrations/``.
Each migration file defines:

- ``dependencies``: list of (app, migration_name) this migration depends on
- ``operations``: list of Operation objects to apply/revert

This module handles:
1. Discovering existing migration files
2. Comparing with the migrations table to find un-applied ones
3. Executing ``up()`` / ``down()`` SQL within transactions
4. Enhanced terminal logging with color-coded status indicators
"""

from __future__ import annotations

import functools
import importlib
import importlib.util
import logging
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.utils import timezone

logger = logging.getLogger("openviper.migrations")


# ── Enhanced Terminal Logging ─────────────────────────────────────────────────


class MigrationStatus(Enum):
    """Migration execution status."""

    OK = "OK"
    SKIP = "SKIP"
    ERROR = "ERROR"
    PENDING = "PENDING"
    ROLLBACK = "ROLLBACK"


class _MigrationLogger:
    """Enhanced logging for migrations with color-coded output."""

    # ANSI color codes for terminal output
    COLORS = {
        "GREEN": "\033[92m",
        "RED": "\033[91m",
        "YELLOW": "\033[93m",
        "BLUE": "\033[94m",
        "CYAN": "\033[96m",
        "BOLD": "\033[1m",
        "END": "\033[0m",
    }

    @classmethod
    def _supports_color(cls) -> bool:
        """Check if terminal supports color."""
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def _colorize(cls, text: str, color: str) -> str:
        """Colorize text if terminal supports it."""
        if cls._supports_color():
            return f"{cls.COLORS.get(color, '')}{text}{cls.COLORS['END']}"
        return text

    @classmethod
    def log_applying(cls, app_name: str, migration_name: str) -> None:
        """Log migration start (no newline)."""
        msg = f"Applying {app_name} - {migration_name} ... "
        print(cls._colorize(msg, "CYAN"), end="", flush=True)

    @classmethod
    def log_status(cls, status: MigrationStatus, error: str | None = None) -> None:
        """Log migration status after applying."""
        if status == MigrationStatus.OK:
            print(cls._colorize("✓ OK", "GREEN"))
        elif status == MigrationStatus.SKIP:
            print(cls._colorize("⊘ SKIP", "YELLOW"))
        elif status == MigrationStatus.ERROR:
            print(cls._colorize("✗ ERROR", "RED"))
            if error:
                print(f"  {cls._colorize(f'Error: {error}', 'RED')}")
        elif status == MigrationStatus.ROLLBACK:
            print(cls._colorize("⬅ ROLLBACK", "BLUE"))
        else:
            print(cls._colorize("⋯ PENDING", "BLUE"))

    @classmethod
    def log_summary(cls, migrations: list[tuple[str, str, MigrationStatus]]) -> None:
        """Log summary of all migrations."""
        print("\n" + "=" * 70)
        print(cls._colorize("Migration Summary", "BOLD"))
        print("=" * 70)

        stats = {
            MigrationStatus.OK: 0,
            MigrationStatus.SKIP: 0,
            MigrationStatus.ERROR: 0,
            MigrationStatus.ROLLBACK: 0,
        }

        for _, _, status in migrations:
            if status in stats:
                stats[status] += 1

        total = sum(stats.values())

        print(f"\nTotal migrations: {total}")
        print(f"  {cls._colorize(f'✓ OK: {stats[MigrationStatus.OK]}', 'GREEN')}")
        print(f"  {cls._colorize(f'⊘ SKIP: {stats[MigrationStatus.SKIP]}', 'YELLOW')}")
        print(f"  {cls._colorize(f'✗ ERROR: {stats[MigrationStatus.ERROR]}', 'RED')}")
        print(f"  {cls._colorize(f'⬅ ROLLBACK: {stats[MigrationStatus.ROLLBACK]}', 'BLUE')}")

        if stats[MigrationStatus.ERROR] == 0:
            print(f"\n{cls._colorize('✓ All migrations completed successfully!', 'GREEN')}\n")
        else:
            print(
                f"\n{cls._colorize('✗ Some migrations failed. Please review errors above.', 'RED')}"
                "\n"
            )


MIGRATION_TABLE_NAME = "openviper_migrations"
SOFT_REMOVED_TABLE_NAME = "openviper_soft_removed_columns"

# ── Migration record ORM (raw SA, no model dependency) ────────────────────────


def _get_migration_table() -> sa.Table:
    meta = get_metadata()
    if MIGRATION_TABLE_NAME in meta.tables:
        return meta.tables[MIGRATION_TABLE_NAME]
    return sa.Table(
        MIGRATION_TABLE_NAME,
        meta,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("app", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            default=lambda: (
                timezone.now().replace(tzinfo=None) if not settings.USE_TZ else timezone.now()
            ),
        ),
    )


def _get_soft_removed_table() -> sa.Table:
    """Return (or create) the table that tracks soft-removed columns.

    Soft-removed columns are columns whose field was removed from the
    model but whose data is preserved in the database by making the
    column nullable.  They are excluded from model validation and save
    operations until the field is reintroduced.
    """
    meta = get_metadata()
    if SOFT_REMOVED_TABLE_NAME in meta.tables:
        return meta.tables[SOFT_REMOVED_TABLE_NAME]
    return sa.Table(
        SOFT_REMOVED_TABLE_NAME,
        meta,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("column_name", sa.String(255), nullable=False),
        sa.Column("column_type", sa.String(100), nullable=False),
        sa.Column("removed_at", sa.DateTime, default=datetime.utcnow),
    )


# ── Dialect helpers ───────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _get_dialect() -> str:
    """Return the database dialect string from settings.

    Possible return values: ``'sqlite'``, ``'postgresql'``, ``'mysql'``.
    Defaults to ``'sqlite'`` if the setting is missing or unrecognised.

    Cached to avoid repeated URL parsing during migration operations.
    """
    try:
        url: str = getattr(settings, "DATABASE_URL", "").lower()
    except Exception:
        url = ""
    if "postgresql" in url or "postgres" in url:
        return "postgresql"
    if "mysql" in url or "mariadb" in url:
        return "mysql"
    if "mssql" in url:
        return "mssql"
    if "oracle" in url:
        return "oracle"
    return "sqlite"


# Per-dialect type mapping: SQLite-specific type names → dialect equivalents.
# Only types that differ across dialects need an entry.
_DIALECT_TYPE_MAP: dict[str, dict[str, str]] = {
    "postgresql": {
        "DATETIME": "TIMESTAMP",
        "BINARY": "BYTEA",
        "TINYINT": "SMALLINT",
        "MEDIUMINT": "INTEGER",
        "DOUBLE": "DOUBLE PRECISION",
        "REAL": "DOUBLE PRECISION",
        "JSON": "JSONB",
        "UUID": "UUID",
    },
    "mysql": {
        "BINARY": "BLOB",
        "BOOLEAN": "TINYINT(1)",
        "UUID": "CHAR(36)",
        "REAL": "DOUBLE",
    },
    "sqlite": {
        "BOOLEAN": "INTEGER",
        "UUID": "TEXT",
        "JSON": "TEXT",
    },
    "mssql": {
        "BOOLEAN": "BIT",
        "UUID": "UNIQUEIDENTIFIER",
        "TEXT": "VARCHAR(MAX)",
        "JSON": "NVARCHAR(MAX)",
        "DATETIME": "DATETIME2",
    },
    "oracle": {
        "BOOLEAN": "NUMBER(1)",
        "TEXT": "CLOB",
        "JSON": "CLOB",
        "UUID": "VARCHAR2(36)",
        "VARCHAR": "VARCHAR2",
        "DATETIME": "TIMESTAMP",
        "INTEGER": "NUMBER",
        "BIGINT": "NUMBER",
    },
}


def _map_column_type(col_type: str, dialect: str) -> str:
    """Translate *col_type* to the canonical form for *dialect*.

    Only the base type name (before any parenthesised length/precision) is
    looked up; the parenthesised suffix is preserved.

    Example: ``_map_column_type("VARCHAR(100)", "postgresql")`` → ``"VARCHAR(100)"``
             ``_map_column_type("DATETIME", "postgresql")`` → ``"TIMESTAMP"``
    """
    mapping = _DIALECT_TYPE_MAP.get(dialect, {})
    if not mapping:
        return col_type
    # Split off any parenthesised suffix so we match "DATETIME" in "DATETIME".
    m = re.match(r"^([A-Z_]+)(\(.*\))?$", col_type.strip().upper())
    if m:

        base, suffix = m.group(1), m.group(2) or ""
        if dialect == "postgresql" and base == "DATETIME" and getattr(settings, "USE_TZ", False):
            return "TIMESTAMP WITH TIME ZONE" + suffix

        if base in mapping:
            return mapping[base] + suffix
    return col_type


# ── Operation primitives ──────────────────────────────────────────────────────


@dataclass
class Operation:
    """Base migration operation."""

    def forward_sql(self) -> list[Any]:
        return []

    def backward_sql(self) -> list[Any]:
        return []


def _quote_identifier(name: str, dialect: str) -> str:
    """Quote a table or column name based on the database dialect."""
    if dialect == "mysql":
        return f"`{name}`"
    if dialect == "mssql":
        return f"[{name.replace(']', ']]')}]"
    return f'"{name}"'


# Valid ON DELETE actions for foreign key constraints.
# Used to whitelist the on_delete value before SQL interpolation.
_VALID_ON_DELETE_ACTIONS: frozenset[str] = frozenset(
    {"CASCADE", "RESTRICT", "SET NULL", "SET DEFAULT", "NO ACTION"}
)


@dataclass
class RenameTable(Operation):
    """Rename an existing table."""

    old_name: str
    new_name: str

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_old = _quote_identifier(self.old_name, dialect)
        quoted_new = _quote_identifier(self.new_name, dialect)
        if dialect == "mysql":
            return [f"RENAME TABLE {quoted_old} TO {quoted_new}"]
        if dialect == "mssql":
            old_escaped = self.old_name.replace("'", "''")
            new_escaped = self.new_name.replace("'", "''")
            return [f"EXEC sp_rename N'{old_escaped}', N'{new_escaped}', 'OBJECT'"]
        # PostgreSQL/SQLite/Oracle
        return [f"ALTER TABLE {quoted_old} RENAME TO {quoted_new}"]

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_old = _quote_identifier(self.old_name, dialect)
        quoted_new = _quote_identifier(self.new_name, dialect)
        if dialect == "mysql":
            return [f"RENAME TABLE {quoted_new} TO {quoted_old}"]
        if dialect == "mssql":
            old_escaped = self.old_name.replace("'", "''")
            new_escaped = self.new_name.replace("'", "''")
            return [f"EXEC sp_rename N'{new_escaped}', N'{old_escaped}', 'OBJECT'"]
        return [f"ALTER TABLE {quoted_new} RENAME TO {quoted_old}"]


@dataclass
class CreateTable(Operation):
    table_name: str
    columns: list[dict[str, Any]] = field(default_factory=list)

    def forward_sql(self) -> list[Any]:
        dialect = _get_dialect()
        cols: list[str] = []
        fk_columns: list[str] = []  # Track FK columns for index creation

        for col in self.columns:
            raw_type = _map_column_type(col["type"], dialect)
            # PostgreSQL uses SERIAL for auto-incrementing integer primary keys
            if (
                dialect == "postgresql"
                and col.get("primary_key")
                and col.get("autoincrement")
                and raw_type.upper() == "INTEGER"
            ):
                raw_type = "SERIAL"

            quoted_name = _quote_identifier(col["name"], dialect)
            definition = f"  {quoted_name} {raw_type}"
            if col.get("primary_key"):
                definition += " PRIMARY KEY"

            # Auto-increment handling
            if col.get("autoincrement"):
                if dialect == "sqlite":
                    definition += " AUTOINCREMENT"
                elif dialect == "mysql":
                    definition += " AUTO_INCREMENT"
                elif dialect == "mssql":
                    definition += " IDENTITY(1,1)"
                elif dialect == "oracle":
                    definition += " GENERATED BY DEFAULT AS IDENTITY"
                # PostgreSQL SERIAL handles it implicitly

            if not col.get("nullable", True):
                definition += " NOT NULL"
            if col.get("unique"):
                definition += " UNIQUE"
            if col.get("default") is not None:
                definition += f" DEFAULT {col['default']!r}"

            # Foreign Key support
            if col.get("target_table"):
                target = col["target_table"]
                on_delete = col.get("on_delete", "CASCADE").upper()
                if on_delete not in _VALID_ON_DELETE_ACTIONS:
                    raise ValueError(
                        f"Invalid ON DELETE action {on_delete!r}. "
                        f"Must be one of: {', '.join(sorted(_VALID_ON_DELETE_ACTIONS))}"
                    )
                definition += (
                    f" REFERENCES {_quote_identifier(target, dialect)}(id) ON DELETE {on_delete}"
                )
                # Track FK column for automatic index creation (performance optimization)
                fk_columns.append(col["name"])

            cols.append(definition)

        col_str = ",\n".join(cols)
        quoted_table = _quote_identifier(self.table_name, dialect)

        stmts: list[Any] = []
        if dialect == "mssql":
            table_escaped = self.table_name.replace("'", "''")
            stmts.append(
                f"IF OBJECT_ID(N'{table_escaped}', N'U') IS NULL\n"
                f"CREATE TABLE {quoted_table} (\n{col_str}\n)"
            )
        else:
            stmts.append(f"CREATE TABLE IF NOT EXISTS {quoted_table} (\n{col_str}\n)")

        # Automatically create indexes on FK columns for query performance
        # FK columns are frequently used in JOINs and WHERE clauses
        for fk_col in fk_columns:
            idx_name = f"idx_{self.table_name}_{fk_col}"
            quoted_idx = _quote_identifier(idx_name, dialect)
            quoted_col = _quote_identifier(fk_col, dialect)

            if dialect == "mssql":
                idx_escaped = idx_name.replace("'", "''")
                stmts.append(
                    f"IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = N'{idx_escaped}')\n"  # nosec B608
                    f"CREATE INDEX {quoted_idx} ON {quoted_table} ({quoted_col})"
                )
            else:
                stmts.append(
                    f"CREATE INDEX IF NOT EXISTS {quoted_idx} ON {quoted_table} ({quoted_col})"
                )

        return stmts

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        return [f"DROP TABLE IF EXISTS {quoted_table}"]


@dataclass
class DropTable(Operation):
    table_name: str

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        if dialect == "mssql":
            table_escaped = self.table_name.replace("'", "''")
            return [f"IF OBJECT_ID(N'{table_escaped}', N'U') IS NOT NULL DROP TABLE {quoted_table}"]
        return [f"DROP TABLE IF EXISTS {quoted_table}"]

    def backward_sql(self) -> list[str]:
        return []  # Cannot recover dropped table


@dataclass
class AddColumn(Operation):
    table_name: str
    column_name: str
    column_type: str
    nullable: bool = True
    default: Any = None

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        raw_type = _map_column_type(self.column_type, dialect)
        if dialect == "mssql":
            sql = f"ALTER TABLE {quoted_table} ADD {quoted_column} {raw_type}"
        else:
            sql = f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {raw_type}"
        if not self.nullable:
            sql += " NOT NULL"
        if self.default is not None:
            sql += f" DEFAULT {self.default!r}"
        return [sql]

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        return [f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}"]


@dataclass
class RemoveColumn(Operation):
    """Soft-remove a column from a table.

    By default the column is made **nullable** and registered in the
    ``openviper_soft_removed_columns`` tracking table.  The column remains
    in the database so existing data is preserved, but it is excluded
    from model validation and save operations.

    Pass ``drop=True`` to permanently DROP the column instead (data
    loss!).
    """

    table_name: str
    column_name: str
    column_type: str = "TEXT"
    drop: bool = False

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        if self.drop:
            return [f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}"]
        # Only track in soft-removed table; do not alter the column in DB.
        # We also quote the soft-removed table name just in case.
        quoted_soft_table = _quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(  # type: ignore[list-item]
                f"INSERT INTO {quoted_soft_table} "  # nosec B608
                "(table_name, column_name, column_type, removed_at) "
                "VALUES (:table_name, :column_name, :column_type, CURRENT_TIMESTAMP)"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
                column_type=self.column_type,
            )
        ]

    def backward_sql(self) -> list[Any]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        if self.drop:
            if dialect == "mssql":
                return [f"ALTER TABLE {quoted_table} ADD {quoted_column} {self.column_type}"]
            return [f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {self.column_type}"]
        # Remove from soft-removed tracking (re-enable the column)
        quoted_soft_table = _quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        stmts: list[Any] = [
            sa.text(
                f"DELETE FROM {quoted_soft_table} "  # nosec B608
                "WHERE table_name = :table_name "
                "AND column_name = :column_name"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
            )
        ]
        return stmts


@dataclass
class RestoreColumn(Operation):
    """Restore a previously soft-removed column back into active use.

    Removes the column from the ``openviper_soft_removed_columns`` tracking
    table so the ORM starts including it in validation and save
    operations again.
    """

    table_name: str
    column_name: str
    column_type: str = "TEXT"

    def forward_sql(self) -> list[Any]:
        dialect = _get_dialect()
        quoted_soft_table = _quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(
                f"DELETE FROM {quoted_soft_table} "  # nosec B608
                "WHERE table_name = :table_name "
                "AND column_name = :column_name"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
            )
        ]

    def backward_sql(self) -> list[Any]:
        dialect = _get_dialect()
        quoted_soft_table = _quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(
                f"INSERT INTO {quoted_soft_table} "  # nosec B608
                "(table_name, column_name, column_type, removed_at) "
                "VALUES (:table_name, :column_name, :column_type, CURRENT_TIMESTAMP)"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
                column_type=self.column_type,
            )
        ]


@dataclass
class AlterColumn(Operation):
    """Alter an existing column's type, nullability, default, or uniqueness."""

    table_name: str
    column_name: str
    column_type: str | None = None
    nullable: bool | None = None
    default: Any = None
    old_type: str | None = None
    old_nullable: bool | None = None
    old_default: Any = None
    using: str | None = None  # PostgreSQL USING clause for type conversions

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        stmts: list[str] = []
        if self.column_type and self.column_type != self.old_type:
            raw_type = _map_column_type(self.column_type, dialect)
            if dialect == "postgresql":
                # Validate USING clause to prevent SQL injection
                if self.using:
                    # Only allow safe column references and type casts
                    safe_using_pattern = re.compile(
                        r"^[a-zA-Z_][a-zA-Z0-9_]*(::[a-zA-Z_][a-zA-Z0-9_]*)?$"
                    )
                    if not safe_using_pattern.match(self.using.strip()):
                        raise ValueError(
                            f"Invalid USING expression '{self.using}'. "
                            "Only simple column references and type casts are allowed "
                            "(e.g., 'column_name::integer')"
                        )
                    using_clause = f" USING {self.using}"
                else:
                    using_clause = ""
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN"
                    f" {quoted_column} TYPE {raw_type}{using_clause}"
                )
            elif dialect == "mysql":
                stmts.append(f"ALTER TABLE {quoted_table} MODIFY COLUMN {quoted_column} {raw_type}")
            elif dialect == "oracle":
                stmts.append(f"ALTER TABLE {quoted_table} MODIFY {quoted_column} {raw_type}")
            elif dialect == "mssql":
                stmts.append(f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} {raw_type}")
            else:
                # SQLite doesn't support ALTER COLUMN natively.
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} TYPE {raw_type}"
                )

        if self.nullable is not None and self.nullable != self.old_nullable:
            if dialect == "postgresql":
                action = "DROP NOT NULL" if self.nullable else "SET NOT NULL"
                stmts.append(f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} {action}")
            elif dialect in ("mysql", "mssql", "oracle"):
                # MySQL/MSSQL/Oracle nullable is part of MODIFY COLUMN;
                raw_type = _map_column_type(self.column_type or self.old_type or "TEXT", dialect)
                null_str = "NULL" if self.nullable else "NOT NULL"
                if dialect == "oracle":
                    stmts.append(
                        f"ALTER TABLE {quoted_table} MODIFY {quoted_column} {raw_type} {null_str}"
                    )
                elif dialect == "mssql":
                    stmts.append(
                        f"ALTER TABLE {quoted_table} ALTER COLUMN"
                        f" {quoted_column} {raw_type} {null_str}"
                    )
                else:
                    stmts.append(
                        f"ALTER TABLE {quoted_table} MODIFY COLUMN"
                        f" {quoted_column} {raw_type} {null_str}"
                    )

        if self.default is not None:
            if dialect in ("postgresql", "mysql"):
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN"
                    f" {quoted_column} SET DEFAULT {self.default!r}"
                )
            elif dialect == "mssql":
                stmts.append(
                    f"ALTER TABLE {quoted_table} ADD DEFAULT {self.default!r} FOR {quoted_column}"
                )
        return stmts

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_column = _quote_identifier(self.column_name, dialect)
        stmts: list[str] = []
        if self.old_type and self.old_type != self.column_type:
            raw_type = _map_column_type(self.old_type, dialect)
            if dialect == "postgresql":
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} TYPE {raw_type}"
                )
            elif dialect == "mysql":
                stmts.append(f"ALTER TABLE {quoted_table} MODIFY COLUMN {quoted_column} {raw_type}")
            elif dialect == "oracle":
                stmts.append(f"ALTER TABLE {quoted_table} MODIFY {quoted_column} {raw_type}")
            elif dialect == "mssql":
                stmts.append(f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} {raw_type}")
            else:
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} TYPE {raw_type}"
                )
        if self.old_nullable is not None and self.old_nullable != self.nullable:
            if dialect == "postgresql":
                action = "DROP NOT NULL" if self.old_nullable else "SET NOT NULL"
                stmts.append(f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} {action}")
            elif dialect in ("mysql", "mssql", "oracle"):
                raw_type = _map_column_type(self.old_type or self.column_type or "TEXT", dialect)
                null_str = "NULL" if self.old_nullable else "NOT NULL"
                if dialect == "oracle":
                    stmts.append(
                        f"ALTER TABLE {quoted_table} MODIFY {quoted_column} {raw_type} {null_str}"
                    )
                elif dialect == "mssql":
                    stmts.append(
                        f"ALTER TABLE {quoted_table} ALTER COLUMN"
                        f" {quoted_column} {raw_type} {null_str}"
                    )
                else:
                    stmts.append(
                        f"ALTER TABLE {quoted_table} MODIFY COLUMN"
                        f" {quoted_column} {raw_type} {null_str}"
                    )
        if self.old_default is not None:
            if dialect in ("postgresql", "mysql"):
                stmts.append(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN"
                    f" {quoted_column} SET DEFAULT {self.old_default!r}"
                )
            elif dialect == "mssql":
                stmts.append(
                    f"ALTER TABLE {quoted_table} ADD DEFAULT"
                    f" {self.old_default!r} FOR {quoted_column}"
                )
        return stmts


@dataclass
class RenameColumn(Operation):
    table_name: str
    old_name: str
    new_name: str

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_old = _quote_identifier(self.old_name, dialect)
        quoted_new = _quote_identifier(self.new_name, dialect)
        if dialect == "mssql":
            # Use parameterized query for sp_rename to prevent SQL injection
            # Note: sp_rename requires string literals, so we validate identifiers strictly
            identifier_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")
            if not identifier_pattern.match(self.table_name):
                raise ValueError(f"Invalid table name: {self.table_name}")
            if not identifier_pattern.match(self.old_name):
                raise ValueError(f"Invalid column name: {self.old_name}")
            if not identifier_pattern.match(self.new_name):
                raise ValueError(f"Invalid column name: {self.new_name}")

            # Safe after validation - identifiers cannot contain quotes or special chars
            return [
                f"EXEC sp_rename N'{self.table_name}.{self.old_name}', N'{self.new_name}', 'COLUMN'"
            ]
        return [f"ALTER TABLE {quoted_table} RENAME COLUMN {quoted_old} TO {quoted_new}"]

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_old = _quote_identifier(self.old_name, dialect)
        quoted_new = _quote_identifier(self.new_name, dialect)
        if dialect == "mssql":
            # Validate identifiers to prevent SQL injection
            identifier_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")
            if not identifier_pattern.match(self.table_name):
                raise ValueError(f"Invalid table name: {self.table_name}")
            if not identifier_pattern.match(self.old_name):
                raise ValueError(f"Invalid column name: {self.old_name}")
            if not identifier_pattern.match(self.new_name):
                raise ValueError(f"Invalid column name: {self.new_name}")

            return [
                f"EXEC sp_rename N'{self.table_name}.{self.new_name}', N'{self.old_name}', 'COLUMN'"
            ]
        return [f"ALTER TABLE {quoted_table} RENAME COLUMN {quoted_new} TO {quoted_old}"]


@dataclass
class CreateIndex(Operation):
    table_name: str
    index_name: str
    columns: list[str]
    unique: bool = False

    def forward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(self.table_name, dialect)
        quoted_index = _quote_identifier(self.index_name, dialect)
        quoted_cols = ", ".join(_quote_identifier(c, dialect) for c in self.columns)
        unique_kw = "UNIQUE " if self.unique else ""
        if dialect == "mssql":
            index_escaped = self.index_name.replace("'", "''")
            table_escaped = self.table_name.replace("'", "''")
            return [
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'{index_escaped}'"  # nosec B608
                f" AND object_id = OBJECT_ID(N'{table_escaped}'))\n"
                f"CREATE {unique_kw}INDEX {quoted_index} ON {quoted_table} ({quoted_cols})"
            ]
        return [
            f"CREATE {unique_kw}INDEX IF NOT EXISTS {quoted_index}"
            f" ON {quoted_table} ({quoted_cols})"
        ]

    def backward_sql(self) -> list[str]:
        dialect = _get_dialect()
        quoted_index = _quote_identifier(self.index_name, dialect)
        if dialect == "mssql":
            quoted_table = _quote_identifier(self.table_name, dialect)
            index_escaped = self.index_name.replace("'", "''")
            table_escaped = self.table_name.replace("'", "''")
            return [
                f"IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'{index_escaped}'"  # nosec B608
                f" AND object_id = OBJECT_ID(N'{table_escaped}'))\n"
                f"DROP INDEX {quoted_index} ON {quoted_table}"
            ]
        return [f"DROP INDEX IF EXISTS {quoted_index}"]


@dataclass
class RunSQL(Operation):
    """Arbitrary forward/backward SQL."""

    sql: str
    reverse_sql: str = ""

    def forward_sql(self) -> list[str]:
        return [self.sql]

    def backward_sql(self) -> list[str]:
        return [self.reverse_sql] if self.reverse_sql else []


# ── Migration file loader ─────────────────────────────────────────────────────


@dataclass
class MigrationRecord:
    app: str
    name: str
    dependencies: list[tuple[str, str]]
    operations: list[Operation]
    path: str


# Built-in OpenViper apps that ship their own migrations.
_BUILTIN_APP_PACKAGES: list[str] = [
    "openviper.admin",
    "openviper.auth",
    "openviper.tasks",
]


def _discover_app_migrations(app_dir: Path, records: list[MigrationRecord]) -> None:
    """Load migration files from a single app directory into *records*."""
    migrations_dir = app_dir / "migrations"
    if not migrations_dir.exists():
        return

    for migration_file in sorted(migrations_dir.glob("*.py")):
        if migration_file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(
            f"{app_dir.name}.migrations.{migration_file.stem}", migration_file
        )
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.warning("Could not load migration %s: %s", migration_file, e)
            continue

        records.append(
            MigrationRecord(
                app=app_dir.name,
                name=migration_file.stem,
                dependencies=getattr(mod, "dependencies", []),
                operations=getattr(mod, "operations", []),
                path=str(migration_file),
            )
        )


def discover_migrations(
    apps_dir: str | None = None, resolved_apps: dict[str, str] | None = None
) -> list[MigrationRecord]:
    """Scan all installed apps for migration files.

    Discovers migrations in two places:

    1. **Project apps** — Either from *resolved_apps* dict (preferred) or
       sub-directories of *apps_dir* (legacy).
    2. **Built-in OpenViper apps** — packages listed in
       ``_BUILTIN_APP_PACKAGES`` (e.g. ``openviper.auth``) that ship their
       own migration files.

    Args:
        apps_dir: Root directory to scan for project app packages (legacy).
        resolved_apps: Dict of {app_name: app_path} from AppResolver (preferred).

    Returns:
        List of MigrationRecord objects (built-in apps first, then
        project apps, both sorted alphabetically).
    """
    records: list[MigrationRecord] = []

    # ── 1. Built-in OpenViper app migrations ─────────────────────────────
    for dotted in _BUILTIN_APP_PACKAGES:
        try:
            pkg = importlib.import_module(dotted)
        except Exception as e:
            logger.warning(f"Could not import built-in app package {dotted}: {e}")
            continue
        pkg_file = getattr(pkg, "__file__", None)
        if pkg_file is None:
            continue
        pkg_dir = Path(pkg_file).resolve().parent
        _discover_app_migrations(pkg_dir, records)

    # ── 2. Project app migrations ─────────────────────────────────────
    if resolved_apps:
        # Use resolved apps from AppResolver (flexible structure)
        for _app_name, app_path in sorted(resolved_apps.items()):
            app_dir = Path(app_path)
            if app_dir.is_dir():
                _discover_app_migrations(app_dir, records)
    elif apps_dir:
        # Legacy: scan apps_dir for subdirectories
        apps_path = Path(apps_dir)
        if apps_path.is_dir():
            for app_dir in sorted(apps_path.iterdir()):
                if not app_dir.is_dir():
                    continue
                _discover_app_migrations(app_dir, records)

    return sort_migrations(records)


def sort_migrations(migrations: list[MigrationRecord]) -> list[MigrationRecord]:
    """Sort migrations based on their dependencies using a topological sort (Kahn's algorithm)."""
    # map (app, name) -> MigrationRecord
    lookup = {(m.app, m.name): m for m in migrations}

    # Pre-build position index for O(1) sort-key lookups (avoids O(n) list.index per call).
    migration_order: dict[tuple[str, str], int] = {
        (m.app, m.name): i for i, m in enumerate(migrations)
    }

    # build adjacency list and in-degree count
    adj: dict[tuple[str, str], list[tuple[str, str]]] = {(m.app, m.name): [] for m in migrations}
    in_degree = {(m.app, m.name): 0 for m in migrations}

    for m in migrations:
        node = (m.app, m.name)
        for dep_app, dep_name in m.dependencies:
            dep_node = (dep_app, dep_name)
            if dep_node in lookup:
                adj[dep_node].append(node)
                in_degree[node] += 1

    # Initialize queue with nodes having zero in-degree
    # We sort them by their original index to maintain stability for non-dependent migrations
    queue = deque(
        sorted(
            [node for node, degree in in_degree.items() if degree == 0],
            key=lambda n: migration_order[n],
        )
    )

    sorted_nodes = []
    while queue:
        curr = queue.popleft()
        sorted_nodes.append(curr)

        # Sort neighbors before adding to queue to maintain Stability
        neighbors = sorted(adj[curr], key=lambda n: migration_order[n])
        for neighbor in neighbors:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_nodes) < len(migrations):
        # Circular dependency detected
        remaining = [node for node in in_degree if node not in sorted_nodes]
        logger.warning("Circular dependency detected in migrations: %s", remaining)
        # Append remaining migrations to ensure they aren't lost, even if order is wrong
        for node in remaining:
            sorted_nodes.append(node)

    return [lookup[node] for node in sorted_nodes]


# ── Database introspection helpers ────────────────────────────────────────────


def _get_existing_columns_sync(connection: Any, table_name: str) -> set[str]:
    """Return the set of column names for *table_name* (sync context).

    Uses :func:`sqlalchemy.inspect` so it works across all supported
    database backends.
    """
    try:
        insp = sa.inspect(connection)
        return {col["name"] for col in insp.get_columns(table_name)}
    except (sa.exc.NoSuchTableError, Exception):
        return set()


async def _column_exists(conn: Any, table_name: str, column_name: str) -> bool:
    """Check whether *column_name* already exists in *table_name*."""
    cols = await conn.run_sync(lambda sync_conn: _get_existing_columns_sync(sync_conn, table_name))
    return column_name in cols


_AUTH_USER_MODEL = "openviper.auth.models.User"
_AUTH_USERS_TABLE = "auth_users"


async def _should_skip_forward(conn: Any, op: Operation) -> bool:
    """Return ``True`` if this forward operation should be skipped.

    * ``CreateTable auth_users`` — skip when a custom USER_MODEL is configured.
    * ``AddColumn`` — skip when the column already exists.
    * ``RemoveColumn`` — skip when the column does not exist.
    """
    if isinstance(op, CreateTable) and op.table_name == _AUTH_USERS_TABLE:
        user_model = getattr(settings, "USER_MODEL", _AUTH_USER_MODEL)
        if user_model != _AUTH_USER_MODEL:
            logger.info(
                "  Skipping CreateTable %s: custom USER_MODEL '%s' is configured.",
                _AUTH_USERS_TABLE,
                user_model,
            )
            return True
    if isinstance(op, AddColumn):
        if await _column_exists(conn, op.table_name, op.column_name):
            logger.info(
                "  Skipping AddColumn: %s.%s already exists.",
                op.table_name,
                op.column_name,
            )
            return True
    elif isinstance(op, RemoveColumn) and not await _column_exists(
        conn, op.table_name, op.column_name
    ):
        logger.info(
            "  Skipping RemoveColumn: %s.%s does not exist.",
            op.table_name,
            op.column_name,
        )
        return True
    return False


async def _get_soft_removed_info(
    conn: Any, table_name: str, column_name: str
) -> dict[str, Any] | None:
    """Return soft-removed column info if it exists, else None."""
    try:
        soft_table = _get_soft_removed_table()
        result = await conn.execute(
            sa.select(
                soft_table.c.table_name, soft_table.c.column_name, soft_table.c.column_type
            ).where(
                sa.and_(
                    soft_table.c.table_name == table_name,
                    soft_table.c.column_name == column_name,
                )
            )
        )
        row = result.first()
        if row:
            return {
                "table_name": row.table_name,
                "column_name": row.column_name,
                "column_type": row.column_type,
            }
    except Exception:  # nosec B110
        pass
    return None


async def _count_null_values(conn: Any, table_name: str, column_name: str) -> int:
    """Count rows where the given column is NULL."""
    try:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(table_name, dialect)
        quoted_column = _quote_identifier(column_name, dialect)
        result = await conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {quoted_table} WHERE {quoted_column} IS NULL")  # nosec B608
        )
        row = result.first()
        return row[0] if row else 0
    except Exception:
        return 0


async def _count_total_rows(conn: Any, table_name: str) -> int:
    """Count total rows in a table."""
    try:
        dialect = _get_dialect()
        quoted_table = _quote_identifier(table_name, dialect)
        result = await conn.execute(sa.text(f"SELECT COUNT(*) FROM {quoted_table}"))  # nosec B608
        row = result.first()
        return row[0] if row else 0
    except Exception:  # nosec B110
        return 0


def _normalize_type(col_type: str) -> str:
    """Normalize a SQL column type for comparison.

    Strips parenthesized arguments and uppercases, so
    ``VARCHAR(255)`` and ``VARCHAR(100)`` both become ``VARCHAR``,
    and ``TEXT`` stays ``TEXT``.
    """

    # Remove anything in parentheses
    normalized = re.sub(r"\(.*?\)", "", col_type).strip().upper()
    # Map common aliases
    type_map = {
        "INT": "INTEGER",
        "BOOL": "BOOLEAN",
        "FLOAT": "REAL",
        "DOUBLE": "REAL",
        "STRING": "VARCHAR",
        "CHAR": "VARCHAR",
    }
    return type_map.get(normalized, normalized)


def _types_compatible(old_type: str, new_type: str) -> bool:
    """Check if two SQL column types are compatible for restoration.

    Types are compatible if they normalize to the same base type.
    Incompatible example: TEXT → INTEGER.
    """
    return _normalize_type(old_type) == _normalize_type(new_type)


async def validate_restore_column(
    conn: Any, op: RestoreColumn, new_type: str, new_nullable: bool
) -> str | None:
    """Validate a RestoreColumn operation before execution.

    Checks:
    1. Type compatibility: if the soft-removed column had a different
       base type than the reintroduced field, the migration cannot
       proceed.
    2. Null data: if the reintroduced field is NOT NULL but existing
       rows contain NULL values, the migration cannot proceed.

    Returns:
        An error message string if validation fails, else ``None``.
    """
    soft_info = await _get_soft_removed_info(conn, op.table_name, op.column_name)
    if not soft_info:
        return None  # Not a soft-removed column; nothing to validate

    old_type = soft_info["column_type"]

    # 1. Type compatibility check
    if not _types_compatible(old_type, new_type):
        return (
            f"Cannot restore column '{op.column_name}' on table "
            f"'{op.table_name}': type mismatch.\n"
            f"  Previously removed type: {old_type}\n"
            f"  New field type:          {new_type}\n"
            f"  These types are incompatible. To proceed, either:\n"
            f"    - Use '--drop-columns' to drop the old column and create a new one\n"
            f"    - Manually migrate the data in the column to the new type first"
        )

    # 2. Null data check for NOT NULL reintroduction
    if not new_nullable:
        null_count = await _count_null_values(conn, op.table_name, op.column_name)
        if null_count > 0:
            total = await _count_total_rows(conn, op.table_name)
            return (
                f"Cannot restore column '{op.column_name}' on table "
                f"'{op.table_name}' as NOT NULL.\n"
                f"  {null_count} of {total} rows have NULL values in this column.\n"
                f"  To proceed, either:\n"
                f"    - Set the field as nullable: field_name = FieldType(null=True)\n"
                f"    - Provide a default value: field_name = FieldType(default=...)\n"
                f"    - Manually update NULL rows before migrating:\n"
                f"      UPDATE {op.table_name} SET {op.column_name} = <value> "
                f"WHERE {op.column_name} IS NULL"
            )

    return None


async def _should_skip_backward(conn: Any, op: Operation) -> bool:
    """Return ``True`` if this backward (rollback) operation should be skipped.

    Backward for ``AddColumn`` is DROP; backward for ``RemoveColumn`` is
    (nothing), so we only need to guard the ``AddColumn`` rollback.
    """
    if isinstance(op, AddColumn) and not await _column_exists(conn, op.table_name, op.column_name):
        logger.info(
            "  Skipping rollback DROP: %s.%s does not exist.",
            op.table_name,
            op.column_name,
        )
        return True
    return False


# ── Executor ──────────────────────────────────────────────────────────────────


class MigrationExecutor:
    """Apply and revert database migrations.

    Args:
        apps_dir: Root directory containing app packages (default: 'apps').
            Used for legacy discovery.
        resolved_apps: Dict of {app_name: app_path} from AppResolver (optional).
            Takes precedence over apps_dir if provided.
    """

    def __init__(self, apps_dir: str = "apps", resolved_apps: dict[str, str] | None = None) -> None:
        self.apps_dir = apps_dir
        self.resolved_apps = resolved_apps

    async def _ensure_migration_table(self) -> None:
        table = _get_migration_table()
        soft_table = _get_soft_removed_table()
        engine = await get_engine()
        async with engine.begin() as conn:
            # Create tables individually to avoid metadata.create_all() trying to
            # create all registered models (which may have unfulfilled dependencies)
            await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
            await conn.run_sync(lambda sync_conn: soft_table.create(sync_conn, checkfirst=True))

    async def _applied_migrations(self) -> set[tuple[str, str]]:
        await self._ensure_migration_table()
        table = _get_migration_table()
        engine = await get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(sa.select(table.c.app, table.c.name))
            return {(row.app, row.name) for row in result}

    async def migrate(
        self,
        target_app: str | None = None,
        target_name: str | None = None,
        *,
        verbose: bool = True,
        ignore_errors: bool = False,
    ) -> list[str]:
        """Apply all pending migrations with enhanced logging.

        Args:
            target_app: If set, only migrate this app.
            target_name: If set with target_app, migrate only up to this migration.
            verbose: Enable enhanced terminal logging with color-coded status.

        Returns:
            List of applied migration names (e.g. ``["0001_initial"]``).
        """
        await self._ensure_migration_table()
        all_migrations = discover_migrations(
            apps_dir=self.apps_dir, resolved_apps=self.resolved_apps
        )
        applied = await self._applied_migrations()
        engine = await get_engine()
        table = _get_migration_table()

        newly_applied: list[str] = []
        migration_log: list[tuple[str, str, MigrationStatus]] = []

        if verbose:
            print(f"\n{_MigrationLogger._colorize('Starting migrations...', 'BLUE')}\n")

        for record in all_migrations:
            if target_app and record.app != target_app:
                continue
            key = (record.app, record.name)
            if key in applied:
                continue
            if target_name and record.name > target_name:
                break

            if verbose:
                _MigrationLogger.log_applying(record.app, record.name)

            try:
                async with engine.begin() as conn:
                    for op in record.operations:
                        if await _should_skip_forward(conn, op):
                            continue
                        # Validate RestoreColumn before executing
                        if isinstance(op, RestoreColumn):
                            error = await validate_restore_column(
                                conn,
                                op,
                                new_type=op.column_type,
                                new_nullable=True,  # default; overridden by migration context
                            )
                            if error:
                                raise RuntimeError(error)
                        for sql_stmt in op.forward_sql():
                            stmt = sa.text(sql_stmt) if isinstance(sql_stmt, str) else sql_stmt
                            await conn.execute(stmt)
                    await conn.execute(
                        sa.insert(table).values(
                            app=record.app,
                            name=record.name,
                            applied_at=(
                                timezone.now().replace(tzinfo=None)
                                if not settings.USE_TZ
                                else timezone.now()
                            ),
                        )
                    )
                newly_applied.append(record.name)

                if verbose:
                    _MigrationLogger.log_status(MigrationStatus.OK)
                migration_log.append((record.app, record.name, MigrationStatus.OK))
                logger.info("Applied %s/%s", record.app, record.name)

            except Exception as e:
                if verbose:
                    _MigrationLogger.log_status(MigrationStatus.ERROR, str(e))
                migration_log.append((record.app, record.name, MigrationStatus.ERROR))
                logger.error("Failed to apply %s/%s: %s", record.app, record.name, e)
                if not ignore_errors:
                    raise
                continue

        if verbose and migration_log:
            _MigrationLogger.log_summary(migration_log)

        # Invalidate soft-removed column cache after applying migrations
        if newly_applied:
            from openviper.db.executor import invalidate_soft_removed_cache

            invalidate_soft_removed_cache()

        # Always try to sync content types if auth app is installed
        try:
            installed_apps = getattr(settings, "INSTALLED_APPS", [])
            if "openviper.auth" in installed_apps or "auth" in installed_apps:
                from openviper.auth.utils import sync_content_types

                await sync_content_types()
        except Exception as e:
            logger.warning("Failed to sync content types after migrations: %s", e)

        return newly_applied

    async def rollback(self, app: str, migration_name: str) -> None:
        """Revert a single migration.

        Args:
            app: App name.
            migration_name: Migration file stem (e.g. ``0001_initial``).
        """
        all_migrations = discover_migrations(
            apps_dir=self.apps_dir, resolved_apps=self.resolved_apps
        )
        engine = await get_engine()
        table = _get_migration_table()

        for record in reversed(all_migrations):
            if record.app == app and record.name == migration_name:
                logger.info("Reverting %s/%s ...", app, migration_name)
                async with engine.begin() as conn:
                    for op in reversed(record.operations):
                        if await _should_skip_backward(conn, op):
                            continue
                        for sql_stmt in op.backward_sql():
                            stmt = sa.text(sql_stmt) if isinstance(sql_stmt, str) else sql_stmt
                            await conn.execute(stmt)
                    await conn.execute(
                        sa.delete(table).where(
                            sa.and_(table.c.app == app, table.c.name == migration_name)
                        )
                    )
                logger.info("  Reverted: %s/%s", app, migration_name)
                return

        raise ValueError(f"Migration {app}/{migration_name} not found.")
