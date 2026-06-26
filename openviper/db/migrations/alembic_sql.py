"""SQL generation and validation using Alembic + SQLGlot.

Generates dialect-correct DDL via Alembic's :class:`Operations` API
(which delegates to SQLAlchemy's dialect compiler) and SQLGlot for
identifier quoting, SQL literal formatting, and injection-safe
expression validation.

The dialect is resolved once from the DATABASE_URL and the same
SQLAlchemy dialect instance is reused for all DDL compilation,
ensuring that the correct database syntax (SERIAL vs AUTO_INCREMENT
vs IDENTITY, backtick vs bracket vs double-quote, etc.) is used
throughout the process lifecycle.

Post-processing adds dialect-specific idempotent guards (MSSQL
IF OBJECT_ID, Oracle EXECUTE IMMEDIATE EXCEPTION blocks) that
Alembic's offline mode does not emit by default.  This ensures
re-runs and partial migration runs are safe.
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mssql as mssql_dialect
from sqlalchemy.dialects import mysql, oracle, postgresql, sqlite

from openviper.conf import settings
from openviper.db.constants import (
    DIALECT_TYPE_MAP,
    PG_NEEDS_USING,
    SQL_INJECTION_RE,
    SQLITE,
    UNSET,
    VARCHAR_LENGTH_DIALECTS,
    VARCHAR_TYPES,
)

logger = logging.getLogger("openviper.migrations")

try:
    import sqlglot
    from sqlglot import exp as sqlglot_exp

    sqlglot_available: bool = True
except ImportError:
    sqlglot_available = False

_SA_DIALECTS: dict[str, Any] = {
    "sqlite": sqlite.dialect,
    "postgresql": postgresql.dialect,
    "mysql": mysql.dialect,
    "mssql": mssql_dialect.dialect,
    "oracle": oracle.dialect,
}

_SQLGLOT_DIALECTS: dict[str, str] = {
    "sqlite": "sqlite",
    "postgresql": "postgres",
    "mysql": "mysql",
    "mssql": "tsql",
    "oracle": "oracle",
}

_SAFE_USING_RE: re.Pattern[str] = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*"
    r"(::[a-zA-Z_][a-zA-Z0-9_ ]*(?:\(\d+(?:,\s*\d+)?\))?)"
    r"*$"
)


def pg_auto_using(column_name: str, pg_type: str) -> str:
    """Return a PostgreSQL USING clause when the target type requires one."""
    base = re.match(r"^([A-Z_ ]+)", pg_type.strip().upper())
    base_type = base.group(1).strip() if base else pg_type.upper()
    if base_type in PG_NEEDS_USING:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", column_name):
            return ""
        return f' USING "{column_name}"::{pg_type}'
    return ""


class DialectSQL:
    """Dialect-aware SQL generation backed by Alembic and SQLGlot.

    A single instance is created per resolved dialect and reused for
    all migration DDL generation.  Alembic's offline ``Operations`` API
    compiles DDL through SQLAlchemy's dialect compiler to produce
    dialect-correct SQL for the target database.  Dialect-specific
    post-processing adds idempotent guards where needed.
    """

    def __init__(self, vendor: str) -> None:
        self.vendor = vendor
        self._sa_dialect = self.resolve_sa_dialect(vendor)
        self._sqlglot_dialect = _SQLGLOT_DIALECTS.get(vendor, "")
        self._buffer = io.StringIO()
        self._ctx = MigrationContext(
            self._sa_dialect, None,
            {"as_sql": True, "output_buffer": self._buffer},
        )
        self._ops = Operations(self._ctx)

    @staticmethod
    def resolve_sa_dialect(vendor: str) -> Any:
        """Return a SQLAlchemy dialect instance for *vendor*."""
        dialect_cls = _SA_DIALECTS.get(vendor)
        if dialect_cls is not None:
            return dialect_cls()
        return sqlite.dialect()

    # ── DDL generation via Alembic Operations ────────────────────────

    def create_table(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
        *,
        constraints: list[dict[str, Any]] | None = None,
        unique_together: list[list[str]] | None = None,
        index_together: list[list[str]] | None = None,
        single: bool = False,
    ) -> list[str]:
        """Generate CREATE TABLE DDL via Alembic with idempotent guards."""
        sa_columns: list[Any] = []
        fk_columns: list[str] = []
        for col in columns:
            sa_col = self.build_sa_column(col)
            sa_columns.append(sa_col)
            if col.get("target_table"):
                fk_columns.append(col["name"])

        self._ops.create_table(table_name, *sa_columns)
        stmts = self.flush()

        # Add CHECK constraints (skip for SQLite - it can't ALTER TABLE ADD CONSTRAINT)
        if constraints:
            for constraint in constraints:
                c_type = constraint.get("type", "").upper()
                c_name = constraint.get("name", "")
                if c_type == "CHECK":
                    check_expr = constraint.get("check", "")
                    if check_expr and self.vendor != SQLITE:
                        self._ops.create_check_constraint(c_name, table_name, check_expr)
                        stmts.extend(self.flush())
                elif c_type == "UNIQUE":
                    fields = constraint.get("fields", [])
                    condition = constraint.get("condition", "")
                    if condition:
                        self._ops.create_index(
                            c_name, table_name, fields, unique=True,
                            postgresql_where=condition,
                        )
                    else:
                        self._ops.create_index(
                            c_name, table_name, fields, unique=True,
                        )
                    stmts.extend(self.flush())

        # Auto-index FK columns for query performance
        for fk_col in fk_columns:
            idx_name = f"idx_{table_name}_{fk_col}"
            self._ops.create_index(idx_name, table_name, [fk_col])
            stmts.extend(self.flush())

        # Unique-together indexes
        if unique_together:
            for fields in unique_together:
                idx_name = f"uniq_{table_name}_{'_'.join(fields)}"
                self._ops.create_index(idx_name, table_name, fields, unique=True)
                stmts.extend(self.flush())

        # Index-together indexes
        if index_together:
            for fields in index_together:
                idx_name = f"idx_{table_name}_{'_'.join(fields)}"
                self._ops.create_index(idx_name, table_name, fields)
                stmts.extend(self.flush())

        # Single-row constraint
        if single and self.vendor != SQLITE:
            cn = f"chk_{table_name}_single_row"
            self._ops.create_check_constraint(cn, table_name, "id = 1")
            stmts.extend(self.flush())

        return [self.wrap_idempotent(s, table_name) for s in stmts]

    def build_sa_column(self, col: dict[str, Any]) -> sa.Column:
        """Build a SQLAlchemy Column from a migration column dict."""
        mapped_type = self.map_type(col["type"])
        sa_type = self.parse_sa_type(mapped_type)
        is_autoincrement = col.get("autoincrement", False) or False
        is_primary_key = col.get("primary_key", False)

        kwargs: dict[str, Any] = {
            "primary_key": is_primary_key,
            "nullable": col.get("nullable", True),
            "autoincrement": is_autoincrement,
        }

        column_args: list[Any] = []

        # Oracle requires explicit Identity for autoincrement columns.
        # PostgreSQL uses SERIAL (handled by SQLAlchemy's pg dialect).
        # MySQL uses AUTO_INCREMENT (handled by SQLAlchemy's mysql dialect).
        # SQLite uses AUTOINCREMENT (handled by SQLAlchemy's sqlite dialect).
        # MSSQL uses IDENTITY (handled by SQLAlchemy's mssql dialect).
        if is_autoincrement and is_primary_key and self.vendor == "oracle":
            column_args.append(sa.Identity(always=False))
            kwargs.pop("autoincrement")

        if col.get("unique"):
            kwargs["unique"] = True
        default = col.get("default")
        if default is not None:
            kwargs["default"] = default
        if col.get("target_table") and self.vendor == SQLITE:
            target_table = col["target_table"]
            target_col = col.get("target_column", "id")
            column_args.append(sa.ForeignKey(
                f"{target_table}.{target_col}",
                ondelete=col.get("on_delete", "CASCADE"),
            ))
        return sa.Column(col["name"], sa_type, *column_args, **kwargs)

    def drop_table(self, table_name: str) -> list[str]:
        self._ops.drop_table(table_name)
        return [self.wrap_idempotent(s, table_name) for s in self.flush()]

    def add_column(
        self, table_name: str, column_name: str, column_type: str,
        nullable: bool = True, default: Any = None,
    ) -> list[str]:
        sa_type = self.parse_sa_type(self.map_type(column_type))
        kwargs: dict[str, Any] = {"nullable": nullable}
        if default is not None:
            if isinstance(default, bool):
                if self.vendor in ("mssql", "oracle"):
                    literal = "1" if default else "0"
                else:
                    literal = "TRUE" if default else "FALSE"
                kwargs["server_default"] = sa.text(literal)
            elif isinstance(default, (int, float)):
                kwargs["server_default"] = sa.text(str(default))
            else:
                kwargs["server_default"] = sa.text(self.sql_literal(default))
        if not nullable and default is None and self.vendor == "mssql":
            warnings.warn(
                f"AddColumn '{column_name}' on '{table_name}': adding a"
                " NOT NULL column without a DEFAULT to a table that may"
                " have existing rows will fail on SQL Server."
                " Provide a default value.",
                stacklevel=2,
            )
        col = sa.Column(column_name, sa_type, **kwargs)
        self._ops.add_column(table_name, col)
        return self.flush()

    def remove_column(self, table_name: str, column_name: str) -> list[str]:
        self._ops.drop_column(table_name, column_name)
        return self.flush()

    def restore_add_column(
        self, table_name: str, column_name: str, column_type: str,
    ) -> list[str]:
        """Restore a previously dropped column (rollback of RemoveColumn)."""
        raw_type = self.map_type(column_type)
        sa_type = self.parse_sa_type(raw_type)
        if self.vendor == "mssql":
            quoted_table = self.quote_identifier(table_name)
            quoted_col = self.quote_identifier(column_name)
            return [f"ALTER TABLE {quoted_table} ADD {quoted_col} {raw_type}"]
        col = sa.Column(column_name, sa_type)
        self._ops.add_column(table_name, col)
        return self.flush()

    def rename_column(self, table_name: str, old_name: str, new_name: str) -> list[str]:
        self._ops.alter_column(table_name, old_name, new_column_name=new_name)
        return self.flush()

    def rename_table(self, old_name: str, new_name: str) -> list[str]:
        self._ops.rename_table(old_name, new_name)
        return self.flush()

    def create_index(
        self, table_name: str, index_name: str, columns: list[str],
        unique: bool = False,
    ) -> list[str]:
        self._ops.create_index(index_name, table_name, columns, unique=unique)
        return [self.wrap_idempotent(s, table_name) for s in self.flush()]

    def drop_index(self, index_name: str, table_name: str) -> list[str]:
        self._ops.drop_index(index_name, table_name=table_name)
        return [self.wrap_idempotent(s, table_name) for s in self.flush()]

    def add_check_constraint(
        self, table_name: str, constraint_name: str, check_expr: str,
    ) -> list[str]:
        if self.vendor == SQLITE:
            return []
        self._ops.create_check_constraint(constraint_name, table_name, check_expr)
        return self.flush()

    def drop_check_constraint(
        self, table_name: str, constraint_name: str,
    ) -> list[str]:
        if self.vendor == SQLITE:
            return []
        if self.vendor == "mysql":
            quoted_table = self.quote_identifier(table_name)
            quoted_name = self.quote_identifier(constraint_name)
            return [f"ALTER TABLE {quoted_table} DROP CHECK {quoted_name}"]
        self._ops.drop_constraint(constraint_name, table_name, type_="check")
        return self.flush()

    def add_unique_constraint(
        self, table_name: str, constraint_name: str, columns: list[str],
        condition: str = "",
    ) -> list[str]:
        if condition:
            self._ops.create_index(
                constraint_name, table_name, columns, unique=True,
                postgresql_where=condition,
            )
        else:
            self._ops.create_index(
                constraint_name, table_name, columns, unique=True,
            )
        return [self.wrap_idempotent(s, table_name) for s in self.flush()]

    def drop_unique_constraint(
        self, table_name: str, constraint_name: str,
    ) -> list[str]:
        if self.vendor == "mssql":
            quoted_name = self.quote_identifier(constraint_name)
            quoted_table = self.quote_identifier(table_name)
            return [f"DROP INDEX {quoted_name} ON {quoted_table}"]
        if self.vendor == "postgresql":
            quoted_table = self.quote_identifier(table_name)
            return [
                f"DROP INDEX IF EXISTS {self.quote_identifier(constraint_name)}",
                f"ALTER TABLE {quoted_table} DROP CONSTRAINT IF EXISTS"
                f" {self.quote_identifier(constraint_name)}",
            ]
        if self.vendor == "mysql":
            quoted_table = self.quote_identifier(table_name)
            return [
                f"DROP INDEX IF EXISTS {self.quote_identifier(constraint_name)}"
                f" ON {quoted_table}"
            ]
        if self.vendor == "oracle":
            return [self.wrap_idempotent(
                f"DROP INDEX {self.quote_identifier(constraint_name)}", table_name,
            )]
        return [f"DROP INDEX IF EXISTS {self.quote_identifier(constraint_name)}"]

    def create_foreign_key(
        self, constraint_name: str, table_name: str, column_name: str,
        target_table: str, on_delete: str = "CASCADE",
    ) -> list[str]:
        mssql_on_delete = on_delete
        if self.vendor == "mssql" and on_delete == "CASCADE":
            mssql_on_delete = "NO ACTION"
        self._ops.create_foreign_key(
            constraint_name, table_name, target_table,
            [column_name], ["id"], ondelete=mssql_on_delete,
        )
        return self.flush()

    def alter_column(
        self, table_name: str, column_name: str,
        *,
        target_type: str | None = None,
        source_type: str | None = None,
        target_nullable: bool | None = None,
        source_nullable: bool | None = None,
        target_default: Any = UNSET,
        target_autoincrement: bool | None = None,
        source_autoincrement: bool | None = None,
        target_primary_key: bool | None = None,
        target_unique: bool | None = None,
        using: str | None = None,
        is_forward: bool = True,
    ) -> list[str]:
        """Generate ALTER COLUMN DDL via Alembic with dialect edge cases."""
        kwargs: dict[str, Any] = {}

        ai_changed = (
            target_autoincrement is not None
            and source_autoincrement is not None
            and target_autoincrement != source_autoincrement
        )

        # MSSQL: warn and skip IDENTITY changes - table rebuild required.
        if ai_changed and self.vendor == "mssql":
            logger.warning(
                "SQL Server does not support adding/removing IDENTITY"
                " via ALTER COLUMN on %s.%s. A table rebuild is required.",
                table_name, column_name,
            )

        # SQLite: warn and skip type/autoincrement changes.
        if (
            target_type and target_type != source_type
            and is_forward and self.vendor == SQLITE
        ):
            logger.warning(
                "SQLite does not support native ALTER COLUMN TYPE for"
                " %s.%s to %s. Skipping; schema may be out of sync.",
                table_name, column_name, target_type,
            )
            target_type = None

        if ai_changed and is_forward and self.vendor == SQLITE:
            logger.warning(
                "SQLite does not support ALTER COLUMN to change AUTOINCREMENT"
                " for %s.%s. A table rebuild is required."
                " Run `viperctl rebuild %s`.",
                table_name, column_name, table_name,
            )

        if target_type and target_type != source_type:
            mapped_type = self.map_type(target_type)
            kwargs["type_"] = self.parse_sa_type(mapped_type)
            if source_type:
                kwargs["existing_type"] = self.parse_sa_type(
                    self.map_type(source_type)
                )

            # PostgreSQL: auto-generate USING clause when not explicitly provided.
            if self.vendor == "postgresql" and is_forward:
                if using:
                    if not _SAFE_USING_RE.match(using.strip()):
                        raise ValueError(
                            f"Invalid USING expression '{using}'."
                            " Only simple column references and type casts"
                            " are allowed (e.g., 'column_name::integer')"
                        )
                    kwargs["postgresql_using"] = using
                else:
                    auto = pg_auto_using(column_name, mapped_type)
                    if auto:
                        kwargs["postgresql_using"] = auto

        if target_nullable is not None and target_nullable != source_nullable:
            kwargs["nullable"] = target_nullable
            if source_nullable is not None:
                kwargs["existing_nullable"] = source_nullable

        if target_default is not UNSET:
            if target_default is None:
                kwargs["server_default"] = None
            elif isinstance(target_default, bool):
                if self.vendor in ("mssql", "oracle"):
                    kwargs["server_default"] = sa.text(
                        "1" if target_default else "0"
                    )
                else:
                    kwargs["server_default"] = sa.text(
                        "TRUE" if target_default else "FALSE"
                    )
            elif isinstance(target_default, (int, float)):
                kwargs["server_default"] = sa.text(str(target_default))
            else:
                kwargs["server_default"] = sa.text(
                    self.sql_literal(target_default)
                )

        if ai_changed and self.vendor != "mssql" and self.vendor != SQLITE:
            kwargs["autoincrement"] = target_autoincrement
            kwargs["existing_autoincrement"] = source_autoincrement

        stmts: list[str] = []

        if kwargs:
            self._ops.alter_column(table_name, column_name, **kwargs)
            stmts.extend(self.flush())

        # Handle primary_key changes via separate ALTER TABLE statements.
        if target_primary_key is True:
            pk_name = f"pk_{table_name}_{column_name}"
            self._ops.create_primary_key(pk_name, table_name, [column_name])
            stmts.extend(self.flush())
        elif target_primary_key is False:
            pk_name = f"pk_{table_name}_{column_name}"
            self._ops.drop_constraint(pk_name, table_name, type_="primary")
            stmts.extend(self.flush())

        # Handle unique constraint changes.
        if target_unique is True:
            uq_name = f"uq_{table_name}_{column_name}"
            self._ops.create_unique_constraint(uq_name, table_name, [column_name])
            stmts.extend(self.flush())
        elif target_unique is False:
            uq_name = f"uq_{table_name}_{column_name}"
            self._ops.drop_constraint(uq_name, table_name, type_="unique")
            stmts.extend(self.flush())

        # MSSQL: drop existing default constraint before setting a new one.
        if target_default is not UNSET and self.vendor == "mssql":
            pre_stmts = self.mssql_drop_default_constraint(table_name, column_name)
            if target_default is not None:
                df_name = f"df_{table_name}_{column_name}"
                quoted_df = self.quote_identifier(df_name)
                quoted_table = self.quote_identifier(table_name)
                quoted_col = self.quote_identifier(column_name)
                pre_stmts.append(
                    f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quoted_df}"
                    f" DEFAULT {self.sql_literal(target_default)}"
                    f" FOR {quoted_col}"
                )
            # Replace Alembic's ALTER COLUMN with MSSQL-specific logic
            # since SQL Server doesn't support DEFAULT inline in ALTER COLUMN.
            return pre_stmts

        return stmts

    def mssql_drop_default_constraint(
        self, table_name: str, column_name: str,
    ) -> list[str]:
        """Generate MSSQL statements to drop an existing default constraint."""
        quoted_table = self.quote_identifier(table_name)
        tbl_esc = table_name.replace("'", "''")
        col_esc = column_name.replace("'", "''")
        return [
            f"DECLARE @_df NVARCHAR(256); "
            f"SELECT @_df = dc.name FROM sys.default_constraints dc "
            f"JOIN sys.columns c ON dc.parent_object_id = c.object_id "
            f"AND dc.parent_column_id = c.column_id "
            f"WHERE c.object_id = OBJECT_ID(N'{tbl_esc}') "
            f"AND c.name = N'{col_esc}'; "
            f"IF @_df IS NOT NULL "
            f"EXEC(N'ALTER TABLE {quoted_table} DROP CONSTRAINT [' + @_df + ']')"
        ]

    # ── Deferred FK ──────────────────────────────────────────────────

    def deferred_fk_stmts(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> list[str]:
        """Return ALTER TABLE ADD CONSTRAINT FOREIGN KEY statements.

        SQLite cannot add FK constraints after table creation, so it
        returns an empty list (FKs are kept inline in CREATE TABLE).
        MSSQL converts CASCADE to NO ACTION upfront to avoid cycle errors.
        """
        if self.vendor == SQLITE:
            return []

        stmts: list[str] = []
        for col in columns:
            target = col.get("target_table")
            if not target:
                continue
            col_name = col["name"]
            constraint_name = f"fk_{table_name}_{col_name}"
            on_delete = col.get("on_delete", "CASCADE")
            if self.vendor == "mssql" and on_delete == "CASCADE":
                on_delete = "NO ACTION"
            self._ops.create_foreign_key(
                constraint_name, table_name, target,
                [col_name], ["id"], ondelete=on_delete,
            )
            stmts.extend(self.flush())
        return stmts

    # ── Type mapping ──────────────────────────────────────────────────

    def map_type(self, col_type: str) -> str:
        """Transpile a column type to this dialect's canonical form."""
        if not col_type:
            return col_type
        mapping = DIALECT_TYPE_MAP.get(self.vendor, {})
        if not mapping:
            return col_type
        match = re.match(r"^([A-Z_]+)(\(.*\))?$", col_type.strip().upper())
        if not match:
            return col_type
        base, suffix = match.group(1), match.group(2) or ""

        if (
            self.vendor == "postgresql"
            and base == "DATETIME"
            and getattr(settings, "USE_TZ", False)
        ):
            return "TIMESTAMP WITH TIME ZONE" + suffix
        mapped = mapping.get(base, base)
        if (
            not suffix
            and mapped in VARCHAR_TYPES
            and self.vendor in VARCHAR_LENGTH_DIALECTS
        ):
            return f"{mapped}(255)"
        return mapped + suffix

    def parse_sa_type(self, type_str: str) -> Any:
        """Parse a SQL type string into a SQLAlchemy type object."""
        upper = type_str.upper().strip()
        # Strip parenthetical length/precision suffix for base-type matching.
        base = upper.split("(")[0].strip()
        if upper.startswith("VARCHAR") or upper.startswith("VARCHAR2"):
            return sa.String(length=self.extract_length(type_str))
        if upper.startswith("CHAR") or upper.startswith("NVARCHAR"):
            return sa.String(length=self.extract_length(type_str))
        if base in ("INTEGER", "INT", "SERIAL"):
            return sa.Integer()
        if base in ("BIGINT", "BIGSERIAL"):
            return sa.BigInteger()
        if base == "SMALLINT":
            return sa.SmallInteger()
        if upper == "TINYINT(1)":
            # MySQL/MariaDB represents BOOLEAN as TINYINT(1).
            return sa.Boolean()
        if base == "TINYINT":
            return sa.SmallInteger()
        if base in ("TEXT", "CLOB"):
            return sa.Text()
        if base in ("FLOAT", "REAL", "DOUBLE"):
            return sa.Float()
        if upper == "DOUBLE PRECISION":
            return sa.Float()
        if base in ("BOOLEAN", "BIT"):
            return sa.Boolean()
        if base in ("DATETIME", "DATETIME2", "SMALLDATETIME"):
            return sa.DateTime()
        if upper in ("TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITHOUT TIME ZONE"):
            return sa.DateTime(timezone="WITH TIME ZONE" in upper)
        if base == "TIMESTAMP":
            return sa.DateTime()
        if base == "DATE":
            return sa.Date()
        if base == "TIME":
            return sa.Time()
        if base in ("BLOB", "BYTEA", "BINARY", "VARBINARY"):
            return sa.LargeBinary()
        if base == "JSON":
            return sa.JSON()
        if base == "UUID" or upper.startswith("UNIQUEIDENTIFIER"):
            return sa.Uuid()
        if base in ("NUMERIC", "DECIMAL") or base.startswith("NUMBER"):
            return sa.Numeric()
        return sa.Text()

    @staticmethod
    def extract_length(type_str: str) -> int | None:
        """Extract the length from a type string like VARCHAR(255)."""
        match = re.search(r"\((\d+)\)", type_str)
        return int(match.group(1)) if match else None

    # ── Identifier quoting ────────────────────────────────────────────

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier using this dialect's quoting convention."""
        if self.vendor == "mysql":
            return f"`{name.replace('`', '``')}`"
        if self.vendor == "mssql":
            return f"[{name.replace(']', ']]')}]"
        if self.vendor == "oracle":
            return name.upper()
        return f'"{name.replace(chr(34), chr(34) + chr(34))}"'

    # ── SQL literal formatting ────────────────────────────────────────

    def sql_literal(self, value: object) -> str:
        """Format a Python value as a SQL literal for this dialect."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            if self.vendor in ("mssql", "oracle"):
                return "1" if value else "0"
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if self.vendor == "oracle":
            escaped = str(value).replace("'", "''")
        else:
            escaped = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    # ── SQL expression validation via SQLGlot ────────────────────────

    def validate_sql_expression(self, expr: str) -> bool:
        """Return True if *expr* is a safe SQL expression (no DDL/DML).

        Uses SQLGlot to parse the expression and walk the AST for
        destructive node types.  Falls back to regex validation when
        SQLGlot is not installed or parsing fails.
        """
        if sqlglot_available:
            try:
                tree = sqlglot.parse_one(expr, read=self._sqlglot_dialect)
                for node in tree.walk():
                    if isinstance(
                        node,
                        (
                            sqlglot_exp.Drop,
                            sqlglot_exp.Delete,
                            sqlglot_exp.Insert,
                            sqlglot_exp.Update,
                            sqlglot_exp.Alter,
                        ),
                    ):
                        return False
                return True
            except Exception:
                logger.debug("SQLGlot AST validation failed, falling back to regex", exc_info=True)
        return not SQL_INJECTION_RE.search(expr)

    # ── Idempotent DDL wrapping ──────────────────────────────────────

    def wrap_idempotent(self, sql: str, table_name: str | None = None) -> str:
        """Wrap DDL in dialect-specific idempotent guards.

        MSSQL: ``IF OBJECT_ID/IF NOT EXISTS`` checks against sys tables.
        Oracle: ``BEGIN EXECUTE IMMEDIATE ... EXCEPTION WHEN OTHERS``
        Others: pass through (re-run safety handled by migration tracking).
        """
        if self.vendor == "mssql" and table_name:
            tbl_esc = table_name.replace("'", "''")
            upper = sql.upper().strip()
            if upper.startswith("CREATE TABLE"):
                quoted = self.quote_identifier(table_name)
                inner = sql[sql.index("("):] if "(" in sql else ""
                return (
                    f"IF OBJECT_ID(N'{tbl_esc}', N'U') IS NULL "
                    f"CREATE TABLE {quoted} {inner}"
                )
            if upper.startswith("DROP TABLE"):
                quoted = self.quote_identifier(table_name)
                return (
                    f"IF OBJECT_ID(N'{tbl_esc}', N'U') IS NOT NULL "
                    f"DROP TABLE {quoted}"
                )
            if upper.startswith("CREATE INDEX") or upper.startswith("CREATE UNIQUE INDEX"):
                idx_match = re.search(r"INDEX\s+\[?(\w+)\]?\s+ON", sql, re.IGNORECASE)
                if idx_match:
                    idx_name = idx_match.group(1)
                    idx_esc = idx_name.replace("'", "''")
                    return (
                        f"IF NOT EXISTS (SELECT 1 FROM sys.indexes"
                        f" WHERE name = N'{idx_esc}'"
                        f" AND object_id = OBJECT_ID(N'{tbl_esc}')) "
                        f"{sql}"
                    )
            if upper.startswith("DROP INDEX"):
                idx_match = re.search(r"DROP INDEX\s+\[?(\w+)\]?", sql, re.IGNORECASE)
                if idx_match:
                    idx_name = idx_match.group(1)
                    idx_esc = idx_name.replace("'", "''")
                    quoted_table = self.quote_identifier(table_name)
                    quoted_idx = self.quote_identifier(idx_name)
                    return (
                        f"IF EXISTS (SELECT 1 FROM sys.indexes"
                        f" WHERE name = N'{idx_esc}'"
                        f" AND object_id = OBJECT_ID(N'{tbl_esc}')) "
                        f"DROP INDEX {quoted_idx} ON {quoted_table}"
                    )
        if self.vendor == "oracle":
            upper = sql.upper().strip()
            if any(upper.startswith(p) for p in (
                "CREATE TABLE", "DROP TABLE", "CREATE INDEX",
                "DROP INDEX", "CREATE UNIQUE INDEX",
                "ALTER TABLE",
            )):
                escaped = sql.replace("'", "''")
                return (
                    f"BEGIN\n"
                    f"EXECUTE IMMEDIATE '{escaped}';\n"
                    f"EXCEPTION WHEN OTHERS THEN\n"
                    f"IF SQLCODE NOT IN (-955, -2327, -942, -1418, -1408,"
                    f" -2264, -904) THEN RAISE; END IF;\n"
                    f"END;"
                )
        if self.vendor in ("postgresql", "mysql"):
            upper_s = sql.upper().strip()
            if upper_s.startswith("CREATE UNIQUE INDEX"):
                return re.sub(
                    r"(?i)^CREATE\s+UNIQUE\s+INDEX\s+",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ",
                    sql,
                    count=1,
                )
            if upper_s.startswith("CREATE INDEX"):
                return re.sub(
                    r"(?i)^CREATE\s+INDEX\s+",
                    "CREATE INDEX IF NOT EXISTS ",
                    sql,
                    count=1,
                )
        return sql

    # ── Internal: flush compiled SQL from the output buffer ──────────

    def flush(self) -> list[str]:
        """Extract and clear accumulated SQL from the output buffer.

        Handles dialect-specific terminators (MSSQL ``GO``, Oracle ``/``)
        and preserves multi-statement blocks (Oracle PL/SQL ``BEGIN...END;``)
        that contain internal semicolons.
        """
        output = self._buffer.getvalue()
        self._buffer.seek(0)
        self._buffer.truncate(0)
        if not output.strip():
            return []

        if self.vendor == "oracle":
            return self.flush_oracle(output)
        return self.flush_default(output)

    def flush_default(self, output: str) -> list[str]:
        """Split output on semicolons, stripping GO terminators."""
        stmts: list[str] = []
        for chunk in output.split(";"):
            chunk = chunk.strip()
            if chunk:
                chunk = re.sub(r"\bGO\b\s*$", "", chunk).strip()
                chunk = re.sub(r"^\s*/\s*$", "", chunk).strip()
                if chunk:
                    stmts.append(chunk)
        return stmts

    def flush_oracle(self, output: str) -> list[str]:
        """Split Oracle output preserving PL/SQL BEGIN...END blocks."""
        stmts: list[str] = []
        # Oracle separates with / on its own line, not semicolons.
        for chunk in re.split(r"\n\s*/\s*\n", output):
            chunk = chunk.strip()
            if chunk:
                # Remove trailing standalone semicolons from DDL statements
                chunk = chunk.rstrip(";").strip()
                if chunk:
                    stmts.append(chunk)
        return stmts
