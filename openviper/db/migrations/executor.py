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
import inspect
import logging
import re
import sys
import warnings
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql.base import PGDialect

from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.db.connections import connections
from openviper.db.constants import (
    AUTH_USER_MODEL,
    AUTH_USERS_TABLE,
    BUILTIN_APP_PACKAGES,
    DIALECT_TYPE_MAP,
    MIGRATION_TABLE_NAME,
    MSSQL,
    POSTGRESQL,
    SOFT_REMOVED_TABLE_NAME,
    SQLITE,
    UNSET,
    VARCHAR_LENGTH_DIALECTS,
    VARCHAR_TYPES,
)
from openviper.db.migrations.alembic_sql import DialectSQL
from openviper.db.model_registry import invalidate_soft_removed_cache
from openviper.db.utils import (
    get_default_database_url,
    quote_identifier,
    validate_on_delete,
    validate_sql_expression,
)
from openviper.utils import timezone

for postgis_name in ("geometry", "geography", "point", "polygon", "linestring"):
    PGDialect.ischema_names.setdefault(postgis_name, sa.types.UserDefinedType)

logger = logging.getLogger("openviper.migrations")


async def maybe_await(value: object) -> object:
    """Await coroutine results, otherwise return plain values."""
    if inspect.isawaitable(value):
        return await value
    return value


class MigrationStatus(Enum):
    """Migration execution status."""

    OK = "OK"
    SKIP = "SKIP"
    ERROR = "ERROR"
    ROLLBACK = "ROLLBACK"


class _MigrationLogger:
    """Enhanced logging for migrations with color-coded output."""

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
    def supports_color(cls) -> bool:
        """Check if terminal supports color."""
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def colorize(cls, text: str, color: str) -> str:
        """Colorize text if terminal supports it."""
        if cls.supports_color():
            return f"{cls.COLORS.get(color, '')}{text}{cls.COLORS['END']}"
        return text

    @classmethod
    def log_applying(cls, app_name: str, migration_name: str) -> None:
        """Log migration start (no newline)."""
        msg = f"Applying {app_name} - {migration_name} ... "
        print(cls.colorize(msg, "CYAN"), end="", flush=True)

    @classmethod
    def log_status(cls, status: MigrationStatus, error: str | None = None) -> None:
        """Log migration status after applying."""
        if status == MigrationStatus.OK:
            print(cls.colorize("✓ OK", "GREEN"))
        elif status == MigrationStatus.SKIP:
            print(cls.colorize("⊘ SKIP", "YELLOW"))
        elif status == MigrationStatus.ERROR:
            print(cls.colorize("✗ ERROR", "RED"))
            if error:
                print(f"  {cls.colorize(f'Error: {error}', 'RED')}")
        elif status == MigrationStatus.ROLLBACK:
            print(cls.colorize("⬅ ROLLBACK", "BLUE"))
        else:
            print(cls.colorize("⋯ PENDING", "BLUE"))

    @classmethod
    def log_summary(cls, migrations: list[tuple[str, str, MigrationStatus]]) -> None:
        """Log summary of all migrations."""
        print("\n" + "=" * 70)
        print(cls.colorize("Migration Summary", "BOLD"))
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
        print(f"  {cls.colorize(f'✓ OK: {stats[MigrationStatus.OK]}', 'GREEN')}")
        print(f"  {cls.colorize(f'⊘ SKIP: {stats[MigrationStatus.SKIP]}', 'YELLOW')}")
        print(f"  {cls.colorize(f'✗ ERROR: {stats[MigrationStatus.ERROR]}', 'RED')}")
        print(f"  {cls.colorize(f'⬅ ROLLBACK: {stats[MigrationStatus.ROLLBACK]}', 'BLUE')}")

        if stats[MigrationStatus.ERROR] == 0:
            print(f"\n{cls.colorize('✓ All migrations completed successfully!', 'GREEN')}\n")
        else:
            print(
                f"\n{cls.colorize('✗ Some migrations failed. Please review errors above.', 'RED')}"
                "\n"
            )


def get_migration_table() -> sa.Table:
    meta = get_metadata()
    if MIGRATION_TABLE_NAME in meta.tables:
        return meta.tables[MIGRATION_TABLE_NAME]
    return sa.Table(
        MIGRATION_TABLE_NAME,
        meta,
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "oracle"),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("app", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            default=timezone.now,
        ),
    )


def get_soft_removed_table() -> sa.Table:
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
        sa.Column("removed_at", sa.DateTime(timezone=True), default=timezone.now),
    )


@functools.lru_cache(maxsize=1)
def get_dialect() -> str:
    """Return the database dialect string from settings.

    Possible return values: ``'sqlite'``, ``'postgresql'``, ``'mysql'``,
    ``'mssql'``, ``'oracle'``.
    Defaults to ``'sqlite'`` if the setting is missing or unrecognised.

    Cached to avoid repeated URL parsing during migration operations.
    """
    try:
        url: str = get_default_database_url(settings).lower()
    except Exception:
        logger.debug("Failed to read database URL from settings", exc_info=True)
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


def get_generator() -> DialectSQL:
    """Return the resolved :class:`DialectSQL` for the current database.

    Uses Alembic's Operations API for DDL generation (delegating to
    SQLAlchemy's dialect compiler) and SQLGlot for SQL validation.
    The dialect is determined by :func:`get_dialect` which reads the
    DATABASES config.  Only the configured dialect's driver module is
    checked for availability.
    """
    return DialectSQL(get_dialect())


# SQLite type name overrides per dialect.

def needs_varchar_length(mapped_type: str, dialect: str) -> bool:
    """Return whether *mapped_type* requires a default length for *dialect*."""
    return mapped_type in VARCHAR_TYPES and dialect in VARCHAR_LENGTH_DIALECTS


def map_column_type(col_type: str, dialect: str) -> str:
    """Translate *col_type* to the canonical form for *dialect*.

    Only the base type name (before any parenthesised length/precision) is
    looked up; the parenthesised suffix is preserved.

    Example: ``map_column_type("VARCHAR(100)", "postgresql")`` → ``"VARCHAR(100)"``
             ``map_column_type("DATETIME", "postgresql")`` → ``"TIMESTAMP"``
    """
    mapping = DIALECT_TYPE_MAP.get(dialect, {})
    if not mapping:
        return col_type
    m = re.match(r"^([A-Z_]+)(\(.*\))?$", col_type.strip().upper())
    if m:
        base, suffix = m.group(1), m.group(2) or ""
        if dialect == POSTGRESQL and base == "DATETIME" and getattr(settings, "USE_TZ", False):
            return "TIMESTAMP WITH TIME ZONE" + suffix

        mapped = mapping.get(base, base)
        if not suffix and needs_varchar_length(mapped, dialect):
            return f"{mapped}(255)"
        return mapped + suffix
    return col_type


@dataclass
class Operation:
    """Base migration operation."""

    def forward_sql(self) -> list[Any]:
        return []

    def backward_sql(self) -> list[Any]:
        return []


def is_sp_rename(sql_stmt: Any) -> bool:
    """Return True when *sql_stmt* is an MSSQL sp_rename call.

    aiomssql requires sp_rename to run in autocommit mode on some SQL Server
    versions.  MigrationExecutor.migrate() uses this helper to switch isolation
    level before executing the statement.
    """
    return isinstance(sql_stmt, str) and sql_stmt.strip().upper().startswith("EXEC SP_RENAME")


@dataclass
class CreateTable(Operation):
    table_name: str
    columns: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    unique_together: list[list[str]] = field(default_factory=list)
    index_together: list[list[str]] = field(default_factory=list)
    single: bool = False

    def forward_sql(self) -> list[Any]:
        gen = get_generator()
        return gen.create_table(
            self.table_name,
            self.columns,
            constraints=self.constraints,
            unique_together=self.unique_together,
            index_together=self.index_together,
            single=self.single,
        )

    def backward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.drop_table(self.table_name)

    def deferred_fk_stmts(self) -> list[str]:
        """Return ALTER TABLE ADD CONSTRAINT FOREIGN KEY statements for deferred execution.

        These are collected by :meth:`MigrationExecutor.migrate` and applied in a
        second phase after *all* tables across all pending migrations have been
        created.  Deferring FK constraints avoids ``UndefinedTableError`` failures
        caused by circular FK dependencies between apps.

        SQLite cannot do ``ALTER TABLE ... ADD CONSTRAINT FOREIGN KEY`` so it keeps
        inline ``REFERENCES`` in :meth:`forward_sql` and this method returns an
        empty list for that dialect.
        """
        gen = get_generator()
        fk_columns = [
            {
                "name": col["name"],
                "target_table": col.get("target_table"),
                "on_delete": validate_on_delete(
                    col.get("on_delete", "CASCADE"),
                    f"CreateTable.deferred_fk.{self.table_name}.{col['name']}",
                ),
            }
            for col in self.columns
            if col.get("target_table")
        ]
        return gen.deferred_fk_stmts(self.table_name, fk_columns)


@dataclass
class DropTable(Operation):
    table_name: str

    def forward_sql(self) -> list[Any]:
        gen = get_generator()
        return gen.drop_table(self.table_name)


@dataclass
class AddColumn(Operation):
    table_name: str
    column_name: str
    column_type: str
    nullable: bool = True
    default: Any = None

    def forward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.add_column(
            self.table_name, self.column_name,
            self.column_type, self.nullable, self.default,
        )

    def backward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.remove_column(self.table_name, self.column_name)


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
        dialect = get_dialect()
        quoted_table = quote_identifier(self.table_name, dialect)
        quoted_column = quote_identifier(self.column_name, dialect)
        if self.drop:
            return [f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}"]
        quoted_soft_table = quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(
                f"INSERT INTO {quoted_soft_table} "
                "(table_name, column_name, column_type, removed_at) "
                "VALUES (:table_name, :column_name, :column_type, CURRENT_TIMESTAMP)"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
                column_type=self.column_type,
            )
        ]

    def backward_sql(self) -> list[Any]:
        gen = get_generator()
        if self.drop:
            return gen.restore_add_column(
                self.table_name, self.column_name, self.column_type
            )
        quoted_soft_table = gen.quote_identifier(SOFT_REMOVED_TABLE_NAME)
        stmts: list[Any] = [
            sa.text(
                f"DELETE FROM {quoted_soft_table} "
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
        dialect = get_dialect()
        quoted_soft_table = quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(
                f"DELETE FROM {quoted_soft_table} "
                "WHERE table_name = :table_name "
                "AND column_name = :column_name"
            ).bindparams(
                table_name=self.table_name,
                column_name=self.column_name,
            )
        ]

    def backward_sql(self) -> list[Any]:
        dialect = get_dialect()
        quoted_soft_table = quote_identifier(SOFT_REMOVED_TABLE_NAME, dialect)
        return [
            sa.text(
                f"INSERT INTO {quoted_soft_table} "
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
    """Alter an existing column's type, nullability, default, autoincrement, or primary key.

    ``default`` uses ``UNSET`` as the sentinel for "no change".  When
    ``default`` is ``None``, the column default is explicitly dropped.
    ``old_default`` follows the same convention.
    """

    table_name: str
    column_name: str
    column_type: str | None = None
    nullable: bool | None = None
    default: Any = field(default_factory=lambda: UNSET)
    old_type: str | None = None
    old_nullable: bool | None = None
    old_default: Any = field(default_factory=lambda: UNSET)
    autoincrement: bool | None = None
    old_autoincrement: bool | None = None
    primary_key: bool | None = None
    old_primary_key: bool | None = None
    unique: bool | None = None
    old_unique: bool | None = None
    using: str | None = None  # PostgreSQL USING clause for type conversions

    def build_alter_sql(
        self,
        target_type: str | None,
        source_type: str | None,
        target_autoincrement: bool | None,
        source_autoincrement: bool | None,
        target_primary_key: bool | None,
        target_nullable: bool | None,
        source_nullable: bool | None,
        target_default: Any,
        target_unique: bool | None,
        is_forward: bool,
    ) -> list[str]:
        """Build ALTER COLUMN SQL statements for either forward or backward.

        The *target_* parameters represent the desired state, and the
        *source_* parameters represent the previous state.
        """
        gen = get_generator()

        # Build a shallow copy with target/source values so the generator
        # can read a uniform interface from self without needing to know
        # whether this is a forward or backward pass.
        return gen.alter_column(
            self.table_name,
            self.column_name,
            target_type=target_type,
            source_type=source_type,
            target_nullable=target_nullable,
            source_nullable=source_nullable,
            target_default=target_default,
            target_autoincrement=target_autoincrement,
            source_autoincrement=source_autoincrement,
            target_primary_key=target_primary_key,
            target_unique=target_unique,
            using=self.using,
            is_forward=is_forward,
        )

    def forward_sql(self) -> list[str]:
        return self.build_alter_sql(
            target_type=self.column_type,
            source_type=self.old_type,
            target_autoincrement=self.autoincrement,
            source_autoincrement=self.old_autoincrement,
            target_primary_key=self.primary_key,
            target_nullable=self.nullable,
            source_nullable=self.old_nullable,
            target_default=self.default,
            target_unique=self.unique,
            is_forward=True,
        )

    def backward_sql(self) -> list[str]:
        return self.build_alter_sql(
            target_type=self.old_type,
            source_type=self.column_type,
            target_autoincrement=self.old_autoincrement,
            source_autoincrement=self.autoincrement,
            target_primary_key=self.old_primary_key,
            target_nullable=self.old_nullable,
            source_nullable=self.nullable,
            target_default=self.old_default,
            target_unique=self.old_unique,
            is_forward=False,
        )


@dataclass
class RenameColumn(Operation):
    table_name: str
    old_name: str
    new_name: str

    def forward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.rename_column(self.table_name, self.old_name, self.new_name)

    def backward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.rename_column(self.table_name, self.new_name, self.old_name)


def build_drop_index_sql(index_name: str, table_name: str) -> list[str]:
    """Return dialect-appropriate ``DROP INDEX`` statements for *index_name*."""
    gen = get_generator()
    return gen.drop_index(index_name, table_name)


@dataclass
class CreateIndex(Operation):
    table_name: str
    index_name: str
    columns: list[str]
    unique: bool = False

    def forward_sql(self) -> list[str]:
        gen = get_generator()
        return gen.create_index(
            self.table_name, self.index_name, self.columns, self.unique,
        )

    def backward_sql(self) -> list[str]:
        return build_drop_index_sql(self.index_name, self.table_name)


@dataclass
class RemoveIndex(Operation):
    """Drop a composite or named index."""

    table_name: str
    index_name: str

    def forward_sql(self) -> list[str]:
        return build_drop_index_sql(self.index_name, self.table_name)

    def backward_sql(self) -> list[str]:
        return []


@dataclass
class AddConstraint(Operation):
    """Add a CHECK or UNIQUE constraint to an existing table."""

    table_name: str
    constraint_name: str
    constraint_type: str
    check: str = ""
    columns: list[str] = field(default_factory=list)
    condition: str = ""

    def forward_sql(self) -> list[str]:
        gen = get_generator()
        if self.constraint_type.upper() == "CHECK":
            validate_sql_expression(self.check, "check", "AddConstraint")
            return gen.add_check_constraint(
                self.table_name, self.constraint_name, self.check,
            )
        if self.constraint_type.upper() == "UNIQUE":
            if self.condition and gen.vendor in (POSTGRESQL, SQLITE):
                validate_sql_expression(self.condition, "condition", "AddConstraint")
            return gen.add_unique_constraint(
                self.table_name, self.constraint_name,
                self.columns, self.condition,
            )
        return []

    def backward_sql(self) -> list[str]:
        gen = get_generator()
        if self.constraint_type.upper() == "UNIQUE":
            return gen.drop_unique_constraint(
                self.table_name, self.constraint_name,
            )
        if self.constraint_type.upper() == "CHECK":
            return gen.drop_check_constraint(
                self.table_name, self.constraint_name,
            )
        return []


@dataclass
class RemoveConstraint(Operation):
    """Remove a previously-added CHECK or UNIQUE constraint."""

    table_name: str
    constraint_name: str
    constraint_type: str = "UNIQUE"

    def forward_sql(self) -> list[str]:
        gen = get_generator()
        if self.constraint_type.upper() == "UNIQUE":
            return gen.drop_unique_constraint(
                self.table_name, self.constraint_name,
            )
        if self.constraint_type.upper() == "CHECK":
            return gen.drop_check_constraint(
                self.table_name, self.constraint_name,
            )
        return []

    def backward_sql(self) -> list[str]:
        return []


@dataclass
class RunSQL(Operation):
    """Arbitrary forward/backward SQL.

    .. warning::

        ``RunSQL`` executes raw SQL without any sanitisation or validation.
        Never interpolate untrusted user input into the ``sql`` or
        ``reverse_sql`` strings - always use parameterised queries or
        validated identifiers for any dynamic portions.  This operation is
        intended for developer-authored migration scripts only.
    """

    sql: str
    reverse_sql: str = ""

    def forward_sql(self) -> list[str]:
        return [self.sql]

    def backward_sql(self) -> list[str]:
        return [self.reverse_sql] if self.reverse_sql else []


@dataclass
class MigrationRecord:
    app: str
    name: str
    dependencies: list[tuple[str, str]]
    operations: list[Operation]
    path: str


def discover_app_migrations(app_dir: Path, records: list[MigrationRecord]) -> None:
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
    """Scan all installed apps for migration files."""
    records: list[MigrationRecord] = []

    for dotted in BUILTIN_APP_PACKAGES:
        try:
            pkg = importlib.import_module(dotted)
        except Exception as e:
            logger.warning("Could not import built-in app package %s: %s", dotted, e)
            continue
        pkg_file = getattr(pkg, "__file__", None)
        if pkg_file is None:
            continue
        pkg_dir = Path(pkg_file).resolve().parent
        discover_app_migrations(pkg_dir, records)

    if resolved_apps:
        for _app_name, app_path in sorted(resolved_apps.items()):
            app_dir = Path(app_path)
            if app_dir.is_dir():
                discover_app_migrations(app_dir, records)
    elif apps_dir:
        apps_path = Path(apps_dir)
        if apps_path.is_dir():
            for app_dir in sorted(apps_path.iterdir()):
                if not app_dir.is_dir():
                    continue
                discover_app_migrations(app_dir, records)

    return sort_migrations(records)


def sort_migrations(migrations: list[MigrationRecord]) -> list[MigrationRecord]:
    """Sort migrations based on their dependencies using a topological sort (Kahn's algorithm)."""
    lookup = {(m.app, m.name): m for m in migrations}

    migration_order: dict[tuple[str, str], int] = {
        (m.app, m.name): i for i, m in enumerate(migrations)
    }

    adj: dict[tuple[str, str], list[tuple[str, str]]] = {(m.app, m.name): [] for m in migrations}
    in_degree = {(m.app, m.name): 0 for m in migrations}

    for m in migrations:
        node = (m.app, m.name)
        for dep_app, dep_name in m.dependencies:
            dep_node = (dep_app, dep_name)
            if dep_node in lookup:
                adj[dep_node].append(node)
                in_degree[node] += 1

    for dep_node in adj:
        adj[dep_node].sort(key=lambda n: migration_order[n])

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

        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_nodes) < len(migrations):
        remaining = [node for node in in_degree if node not in sorted_nodes]
        logger.warning("Circular dependency detected in migrations: %s", remaining)
        for node in remaining:
            sorted_nodes.append(node)

    return [lookup[node] for node in sorted_nodes]


def get_existing_columns_sync(connection: Any, table_name: str) -> set[str]:
    """Return the set of column names for *table_name* (sync context)."""
    try:
        insp = sa.inspect(connection)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Did not recognize type")
            columns = insp.get_columns(table_name)
        return {col["name"] for col in columns}
    except sa.exc.NoSuchTableError:
        return set()
    except Exception:
        logger.debug("Column introspection failed for table %s", table_name, exc_info=True)
        return set()


async def column_exists(conn: Any, table_name: str, column_name: str) -> bool:
    """Check whether *column_name* already exists in *table_name*."""
    cols = await conn.run_sync(lambda sync_conn: get_existing_columns_sync(sync_conn, table_name))
    return column_name in cols


async def should_skip_forward(conn: Any, op: Operation) -> bool:
    """Return ``True`` if this forward operation should be skipped."""
    if isinstance(op, (CreateTable, CreateIndex)) and op.table_name == AUTH_USERS_TABLE:
        user_model = getattr(settings, "USER_MODEL", AUTH_USER_MODEL)
        if user_model != AUTH_USER_MODEL:
            return True
    if isinstance(op, AddColumn):
        if await column_exists(conn, op.table_name, op.column_name):
            logger.info(
                "  Skipping AddColumn: %s.%s already exists.",
                op.table_name,
                op.column_name,
            )
            return True
    elif isinstance(op, RemoveColumn) and not await column_exists(
        conn, op.table_name, op.column_name
    ):
        logger.info(
            "  Skipping RemoveColumn: %s.%s does not exist.",
            op.table_name,
            op.column_name,
        )
        return True
    return False


async def get_soft_removed_info(
    conn: Any, table_name: str, column_name: str
) -> dict[str, Any] | None:
    """Return soft-removed column info if it exists, else None."""
    try:
        soft_table = get_soft_removed_table()
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
        row = await maybe_await(result.first())
        if row:
            return {
                "table_name": row.table_name,
                "column_name": row.column_name,
                "column_type": row.column_type,
            }
    except Exception:
        logger.debug("Column introspection failed for migration check", exc_info=True)
    return None


async def count_null_values(conn: Any, table_name: str, column_name: str) -> int:
    """Count rows where the given column is NULL."""
    try:
        dialect = get_dialect()
        quoted_table = quote_identifier(table_name, dialect)
        quoted_column = quote_identifier(column_name, dialect)
        result = await conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {quoted_table} WHERE {quoted_column} IS NULL")
        )
        row = await maybe_await(result.first())
        return row[0] if row else 0
    except Exception:
        logger.debug("Null value count failed for %s.%s", table_name, column_name, exc_info=True)
        return 0


async def count_total_rows(conn: Any, table_name: str) -> int:
    """Count total rows in a table."""
    try:
        dialect = get_dialect()
        quoted_table = quote_identifier(table_name, dialect)
        result = await conn.execute(sa.text(f"SELECT COUNT(*) FROM {quoted_table}"))
        row = result.first()
        return row[0] if row else 0
    except Exception:
        logger.debug("Total row count failed for table %s", table_name, exc_info=True)
        return 0


def normalize_type(col_type: str) -> str:
    """Normalize a SQL column type for comparison."""
    normalized = re.sub(r"\(.*?\)", "", col_type).strip().upper()
    type_map = {
        "INT": "INTEGER",
        "BOOL": "BOOLEAN",
        "FLOAT": "REAL",
        "DOUBLE": "REAL",
        "STRING": "VARCHAR",
        "CHAR": "VARCHAR",
    }
    return type_map.get(normalized, normalized)


def types_compatible(old_type: str, new_type: str) -> bool:
    """Check if two SQL column types are compatible for restoration."""
    return normalize_type(old_type) == normalize_type(new_type)


async def validate_restore_column(
    conn: Any, op: RestoreColumn, new_type: str, new_nullable: bool
) -> str | None:
    """Validate a RestoreColumn operation before execution."""
    soft_info = await get_soft_removed_info(conn, op.table_name, op.column_name)
    if not soft_info:
        return None

    old_type = soft_info["column_type"]

    if not types_compatible(old_type, new_type):
        return (
            f"Cannot restore column '{op.column_name}' on table "
            f"'{op.table_name}': type mismatch.\n"
            f"  Previously removed type: {old_type}\n"
            f"  New field type:          {new_type}\n"
            f"  These types are incompatible. To proceed, either:\n"
            f"    - Use '--drop-columns' to drop the old column and create a new one\n"
            f"    - Manually migrate the data in the column to the new type first"
        )

    if not new_nullable:
        null_count = await count_null_values(conn, op.table_name, op.column_name)
        if null_count > 0:
            total = await count_total_rows(conn, op.table_name)
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


async def should_skip_backward(conn: Any, op: Operation) -> bool:
    """Return ``True`` if this backward (rollback) operation should be skipped."""
    if isinstance(op, CreateIndex) and op.table_name == AUTH_USERS_TABLE:
        user_model = getattr(settings, "USER_MODEL", AUTH_USER_MODEL)
        if user_model != AUTH_USER_MODEL:
            return True
    if isinstance(op, AddColumn) and not await column_exists(conn, op.table_name, op.column_name):
        logger.info(
            "  Skipping rollback DROP: %s.%s does not exist.",
            op.table_name,
            op.column_name,
        )
        return True
    return False


class MigrationExecutor:
    """Apply and revert database migrations.

    Args:
        apps_dir: Root directory containing app packages (default: 'apps').
        resolved_apps: Dict of {app_name: app_path} from AppResolver (optional).
    """

    def __init__(
        self, apps_dir: str = "apps", resolved_apps: dict[str, str] | None = None
    ) -> None:
        self.apps_dir = apps_dir
        self.resolved_apps = resolved_apps

    async def ensure_migration_table(self, db_alias: str = "default") -> None:
        table = get_migration_table()
        soft_table = get_soft_removed_table()
        engine = await self.get_engine_for_alias(db_alias)
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
            await conn.run_sync(lambda sync_conn: soft_table.create(sync_conn, checkfirst=True))

    async def applied_migrations(self, db_alias: str = "default") -> set[tuple[str, str]]:
        await self.ensure_migration_table(db_alias=db_alias)
        table = get_migration_table()
        engine = await self.get_engine_for_alias(db_alias)
        async with engine.connect() as conn:
            result = await conn.execute(sa.select(table.c.app, table.c.name))
            return {(row.app, row.name) for row in result}

    async def get_engine_for_alias(self, db_alias: str = "default") -> Any:
        """Return the async engine for the given database alias."""
        if db_alias == "default":
            try:
                if connections.initialized and "default" in connections.backends:
                    return await connections.get("default").create_engine()
            except Exception:
                logger.debug(
                    "Backend engine creation failed, falling back to get_engine()",
                    exc_info=True,
                )
        return await get_engine()

    async def _execute_stmt(self, conn: Any, engine: Any, sql_stmt: Any) -> None:
        """Execute a single SQL statement, using autocommit for sp_rename on MSSQL.

        MSSQL / aiomssql fix: sp_rename must run outside an explicit
        transaction on some SQL Server versions.  We detect sp_rename calls
        and re-execute them via a fresh autocommit connection.
        """
        if get_dialect() == MSSQL and is_sp_rename(sql_stmt):
            async with engine.connect() as ac:
                await ac.execution_options(isolation_level="AUTOCOMMIT")
                await ac.execute(sa.text(sql_stmt))
            return
        stmt = sa.text(sql_stmt) if isinstance(sql_stmt, str) else sql_stmt
        await conn.execute(stmt)

    async def migrate(
        self,
        target_app: str | None = None,
        target_name: str | None = None,
        *,
        verbose: bool = True,
        ignore_errors: bool = False,
        database: str | None = None,
    ) -> list[str]:
        """Apply all pending migrations with enhanced logging.

        Args:
            target_app: If set, only migrate this app.
            target_name: If set with target_app, migrate only up to this migration.
            verbose: Enable enhanced terminal logging with color-coded status.
            database: Database alias to run migrations on.  Defaults to ``'default'``.

        Returns:
            List of applied migration names (e.g. ``["0001_initial"]``).
        """
        db_alias = database or "default"
        await self.ensure_migration_table(db_alias=db_alias)
        all_migrations = discover_migrations(
            apps_dir=self.apps_dir, resolved_apps=self.resolved_apps
        )
        applied = await self.applied_migrations(db_alias=db_alias)
        engine = await self.get_engine_for_alias(db_alias)
        table = get_migration_table()

        newly_applied: list[str] = []
        migration_log: list[tuple[str, str, MigrationStatus]] = []
        deferred_fk_stmts: list[str] = []

        if verbose:
            print(f"\n{_MigrationLogger.colorize('Starting migrations...', 'BLUE')}\n")

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
                        if await should_skip_forward(conn, op):
                            continue
                        if isinstance(op, RestoreColumn):
                            error = await validate_restore_column(
                                conn,
                                op,
                                new_type=op.column_type,
                                new_nullable=True,
                            )
                            if error:
                                raise RuntimeError(error)
                        for sql_stmt in op.forward_sql():
                            await self._execute_stmt(conn, engine, sql_stmt)
                        if isinstance(op, CreateTable):
                            deferred_fk_stmts.extend(op.deferred_fk_stmts())
                    await conn.execute(
                        sa.insert(table).values(
                            app=record.app,
                            name=record.name,
                            applied_at=timezone.now(),
                        )
                    )
                newly_applied.append(record.name)

                if verbose:
                    _MigrationLogger.log_status(MigrationStatus.OK)
                migration_log.append((record.app, record.name, MigrationStatus.OK))

            except Exception as e:
                if verbose:
                    _MigrationLogger.log_status(MigrationStatus.ERROR, str(e))
                migration_log.append((record.app, record.name, MigrationStatus.ERROR))
                logger.error("Failed to apply %s/%s: %s", record.app, record.name, e)
                if not ignore_errors:
                    raise
                continue

        # Filter out deferred FK stmts for tables dropped in later migrations
        dropped_tables: set[str] = set()
        for record in all_migrations:
            key = (record.app, record.name)
            if key in applied:
                continue
            for op in record.operations:
                if isinstance(op, DropTable):
                    dropped_tables.add(op.table_name)

        if dropped_tables:
            fk_table_pattern = re.compile(
                r'ALTER TABLE\s+"?(\w+)"?\s+ADD\s+CONSTRAINT', re.IGNORECASE
            )
            filtered: list[str] = []
            for fk_stmt in deferred_fk_stmts:
                m = fk_table_pattern.search(fk_stmt)
                if m and m.group(1) in dropped_tables:
                    logger.debug(
                        "Skipping deferred FK for dropped table '%s': %s",
                        m.group(1),
                        fk_stmt,
                    )
                else:
                    filtered.append(fk_stmt)
            deferred_fk_stmts = filtered

        for fk_stmt in deferred_fk_stmts:
            try:
                async with engine.begin() as conn:
                    await conn.execute(sa.text(fk_stmt))
            except Exception as fk_err:
                err_str = str(fk_err).lower()
                if "already exists" in err_str or "duplicate" in err_str:
                    logger.debug("Deferred FK constraint already exists, skipping: %s", fk_err)
                elif (
                    "1785" in err_str
                    or "multiple cascade paths" in err_str
                    or "cycles or multiple cascade" in err_str
                ):
                    fallback = re.sub(
                        r"\bON\s+DELETE\s+CASCADE\b",
                        "ON DELETE NO ACTION",
                        fk_stmt,
                        flags=re.IGNORECASE,
                    )
                    if fallback != fk_stmt:
                        logger.info(
                            "MSSQL FK cascade cycle (1785) - retrying with NO ACTION: %s",
                            fk_stmt.split("\n")[0][:120],
                        )
                        try:
                            async with engine.begin() as conn:
                                await conn.execute(sa.text(fallback))
                        except Exception as retry_err:
                            logger.warning(
                                "Could not apply deferred FK (NO ACTION fallback): %s", retry_err
                            )
                    else:
                        logger.warning("Could not apply deferred FK constraint: %s", fk_err)
                else:
                    logger.warning("Could not apply deferred FK constraint: %s", fk_err)

        if verbose and migration_log:
            _MigrationLogger.log_summary(migration_log)

        if newly_applied:
            invalidate_soft_removed_cache()

        try:
            installed_apps = getattr(settings, "INSTALLED_APPS", [])
            if "openviper.auth" in installed_apps or "auth" in installed_apps:
                _auth_utils = sys.modules.get("openviper.auth.utils")
                _sync_fn = (
                    getattr(_auth_utils, "sync_content_types", None) if _auth_utils else None
                )
                if _sync_fn is not None:
                    await _sync_fn()
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
        table = get_migration_table()

        for record in reversed(all_migrations):
            if record.app == app and record.name == migration_name:
                logger.info("Reverting %s/%s ...", app, migration_name)
                async with engine.begin() as conn:
                    for op in reversed(record.operations):
                        if await should_skip_backward(conn, op):
                            continue
                        for sql_stmt in op.backward_sql():
                            await self._execute_stmt(conn, engine, sql_stmt)
                    await conn.execute(
                        sa.delete(table).where(
                            sa.and_(table.c.app == app, table.c.name == migration_name)
                        )
                    )
                logger.info("  Reverted: %s/%s", app, migration_name)
                return

        raise ValueError(f"Migration {app}/{migration_name} not found.")
