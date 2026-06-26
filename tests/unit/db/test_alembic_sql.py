"""Tests for Alembic + SQLGlot backed DialectSQL.

Verifies that DDL generation via Alembic's Operations API, type
mapping via DIALECT_TYPE_MAP, identifier quoting, SQL literal
formatting, and SQL expression validation via SQLGlot produce correct
output for each supported dialect.
"""

from __future__ import annotations

import pytest

from openviper.db.migrations.alembic_sql import _SQLGLOT_DIALECTS, DialectSQL


class TestCreateTable:
    @pytest.mark.parametrize("vendor", ["sqlite", "postgresql", "mysql", "mssql", "oracle"])
    def test_creates_table_with_autoincrement_pk(self, vendor: str) -> None:
        gen = DialectSQL(vendor)
        stmts = gen.create_table("users", [
            {
                "name": "id", "type": "INTEGER",
                "primary_key": True, "autoincrement": True,
                "nullable": False,
            },
            {"name": "name", "type": "VARCHAR(100)", "nullable": False},
        ])
        assert len(stmts) >= 1
        ddl = stmts[0]
        assert "CREATE TABLE" in ddl.upper()
        assert "users" in ddl

    def test_postgresql_generates_serial(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.create_table("users", [
            {
                "name": "id", "type": "INTEGER",
                "primary_key": True, "autoincrement": True,
                "nullable": False,
            },
        ])
        assert "SERIAL" in stmts[0]

    def test_mysql_generates_auto_increment(self) -> None:
        gen = DialectSQL("mysql")
        stmts = gen.create_table("users", [
            {
                "name": "id", "type": "INTEGER",
                "primary_key": True, "autoincrement": True,
                "nullable": False,
            },
        ])
        assert "AUTO_INCREMENT" in stmts[0]

    def test_mssql_generates_identity(self) -> None:
        gen = DialectSQL("mssql")
        stmts = gen.create_table("users", [
            {
                "name": "id", "type": "INTEGER",
                "primary_key": True, "autoincrement": True,
                "nullable": False,
            },
        ])
        assert "IDENTITY" in stmts[0]

    def test_oracle_generates_varchar2(self) -> None:
        gen = DialectSQL("oracle")
        stmts = gen.create_table("users", [
            {
                "name": "id", "type": "INTEGER",
                "primary_key": True, "autoincrement": True,
                "nullable": False,
            },
            {"name": "title", "type": "VARCHAR(100)", "nullable": False},
        ])
        assert "VARCHAR2" in stmts[0]

    def test_check_constraint_skipped_for_sqlite(self) -> None:
        gen = DialectSQL("sqlite")
        stmts = gen.add_check_constraint("users", "ck_age", "age > 0")
        assert stmts == []

    def test_check_constraint_added_for_postgresql(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.add_check_constraint("users", "ck_age", "age > 0")
        assert len(stmts) == 1
        assert "CHECK" in stmts[0]
        assert "age > 0" in stmts[0]

    def test_deferred_fk_skipped_for_sqlite(self) -> None:
        gen = DialectSQL("sqlite")
        stmts = gen.deferred_fk_stmts("posts", [
            {"name": "author_id", "target_table": "users", "on_delete": "CASCADE"},
        ])
        assert stmts == []

    def test_deferred_fk_generated_for_postgresql(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.deferred_fk_stmts("posts", [
            {"name": "author_id", "target_table": "users", "on_delete": "CASCADE"},
        ])
        assert len(stmts) == 1
        assert "FOREIGN KEY" in stmts[0]
        assert "CASCADE" in stmts[0]


class TestDropTable:
    def test_drops_table(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.drop_table("users")
        assert "DROP TABLE" in stmts[0].upper()


class TestAddColumn:
    def test_adds_column(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.add_column("users", "bio", "TEXT", nullable=True)
        assert "ADD COLUMN" in stmts[0].upper()
        assert "bio" in stmts[0]

    def test_adds_not_null_with_default(self) -> None:
        gen = DialectSQL("sqlite")
        stmts = gen.add_column("users", "count", "INTEGER", nullable=False, default=0)
        assert "NOT NULL" in stmts[0]
        assert "0" in stmts[0]


class TestRemoveColumn:
    def test_drops_column(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.remove_column("users", "bio")
        assert "DROP COLUMN" in stmts[0].upper()


class TestRenameColumn:
    def test_postgresql_uses_rename_to(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.rename_column("users", "old", "new")
        assert "RENAME" in stmts[0].upper()

    def test_mssql_uses_sp_rename(self) -> None:
        gen = DialectSQL("mssql")
        stmts = gen.rename_column("users", "old", "new")
        assert "sp_rename" in stmts[0].lower()


class TestRenameTable:
    def test_postgresql_uses_rename_to(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.rename_table("users", "accounts")
        assert "RENAME" in stmts[0].upper()

    def test_mssql_uses_sp_rename(self) -> None:
        gen = DialectSQL("mssql")
        stmts = gen.rename_table("users", "accounts")
        assert "sp_rename" in stmts[0].lower()


class TestCreateIndex:
    def test_creates_index(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.create_index("users", "idx_name", ["name"])
        assert "CREATE INDEX" in stmts[0].upper()
        assert "name" in stmts[0]

    def test_creates_unique_index(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.create_index("users", "uq_email", ["email"], unique=True)
        assert "UNIQUE" in stmts[0].upper()


class TestDropIndex:
    def test_drops_index(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.drop_index("idx_name", "users")
        assert "DROP INDEX" in stmts[0].upper()


class TestAddUniqueConstraint:
    def test_adds_unique(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.add_unique_constraint("users", "uq_email", ["email"])
        assert "UNIQUE" in stmts[0].upper()

    def test_adds_unique_with_condition(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.add_unique_constraint("users", "uq_email", ["email"], condition="active = 1")
        assert "UNIQUE" in stmts[0].upper()


class TestDropUniqueConstraint:
    def test_drops_unique(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.drop_unique_constraint("users", "uq_email")
        assert any("DROP INDEX" in s.upper() for s in stmts)


class TestCreateForeignKey:
    def test_creates_fk(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.create_foreign_key(
            "fk_posts_author", "posts", "author_id", "users", on_delete="CASCADE"
        )
        assert "FOREIGN KEY" in stmts[0].upper()
        assert "CASCADE" in stmts[0]


class TestAlterColumn:
    def test_alter_type(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.alter_column(
            "users", "title", target_type="VARCHAR(200)", source_type="VARCHAR(100)",
        )
        assert any("ALTER" in s.upper() for s in stmts)

    def test_alter_nullable(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.alter_column(
            "users", "title", target_nullable=False, source_nullable=True,
        )
        assert any("NOT NULL" in s.upper() for s in stmts)

    def test_no_change_returns_empty(self) -> None:
        gen = DialectSQL("postgresql")
        stmts = gen.alter_column(
            "users", "title",
            target_type="VARCHAR(100)", source_type="VARCHAR(100)",
            target_nullable=True, source_nullable=True,
        )
        assert stmts == []


class TestQuoteIdentifier:
    def test_mysql_uses_backticks(self) -> None:
        gen = DialectSQL("mysql")
        assert gen.quote_identifier("users") == "`users`"

    def test_mssql_uses_brackets(self) -> None:
        gen = DialectSQL("mssql")
        assert gen.quote_identifier("users") == "[users]"

    def test_oracle_uppercases(self) -> None:
        gen = DialectSQL("oracle")
        assert gen.quote_identifier("users") == "USERS"

    def test_postgresql_uses_double_quotes(self) -> None:
        gen = DialectSQL("postgresql")
        assert gen.quote_identifier("users") == '"users"'

    def test_sqlite_uses_double_quotes(self) -> None:
        gen = DialectSQL("sqlite")
        assert gen.quote_identifier("users") == '"users"'


class TestSQLLiteral:
    def test_none_returns_null(self) -> None:
        assert DialectSQL("postgresql").sql_literal(None) == "NULL"

    def test_mssql_boolean_as_one_zero(self) -> None:
        gen = DialectSQL("mssql")
        assert gen.sql_literal(True) == "1"
        assert gen.sql_literal(False) == "0"

    def test_oracle_boolean_as_one_zero(self) -> None:
        gen = DialectSQL("oracle")
        assert gen.sql_literal(True) == "1"
        assert gen.sql_literal(False) == "0"

    def test_postgresql_boolean_as_true_false(self) -> None:
        gen = DialectSQL("postgresql")
        assert gen.sql_literal(True) == "TRUE"
        assert gen.sql_literal(False) == "FALSE"

    def test_integer_passthrough(self) -> None:
        assert DialectSQL("sqlite").sql_literal(42) == "42"

    def test_string_escaped(self) -> None:
        assert DialectSQL("postgresql").sql_literal("it's") == "'it''s'"


class TestValidateSQLExpression:
    def test_safe_expression_returns_true(self) -> None:
        gen = DialectSQL("postgresql")
        assert gen.validate_sql_expression("price > 0") is True

    def test_drop_table_detected(self) -> None:
        gen = DialectSQL("postgresql")
        assert gen.validate_sql_expression("price > 0; DROP TABLE users") is False

    def test_unparseable_falls_back_to_regex(self) -> None:
        gen = DialectSQL("postgresql")
        result = gen.validate_sql_expression("just some text")
        assert isinstance(result, bool)


class TestMapType:
    def test_postgresql_datetime_to_timestamp(self) -> None:
        gen = DialectSQL("postgresql")
        assert "TIMESTAMP" in gen.map_type("DATETIME")

    def test_mssql_boolean_to_bit(self) -> None:
        gen = DialectSQL("mssql")
        assert gen.map_type("BOOLEAN") == "BIT"

    def test_oracle_text_to_clob(self) -> None:
        gen = DialectSQL("oracle")
        assert gen.map_type("TEXT") == "CLOB"

    def test_sqlite_boolean_to_integer(self) -> None:
        gen = DialectSQL("sqlite")
        assert gen.map_type("BOOLEAN") == "INTEGER"

    def test_mysql_uuid_to_char36(self) -> None:
        gen = DialectSQL("mysql")
        assert gen.map_type("UUID") == "CHAR(36)"

    def test_unknown_type_passthrough(self) -> None:
        gen = DialectSQL("postgresql")
        result = gen.map_type("CUSTOMTYPE")
        assert isinstance(result, str)


class TestSQLGlotDialectMapping:
    def test_sqlglot_dialect_names(self) -> None:
        assert _SQLGLOT_DIALECTS["postgresql"] == "postgres"
        assert _SQLGLOT_DIALECTS["mssql"] == "tsql"
        assert _SQLGLOT_DIALECTS["mysql"] == "mysql"
        assert _SQLGLOT_DIALECTS["sqlite"] == "sqlite"
        assert _SQLGLOT_DIALECTS["oracle"] == "oracle"
