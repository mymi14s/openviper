"""Tests for unified per-dialect support, driver availability, and lifecycle.

Verifies that each dialect file correctly implements driver availability
checking, that the dialect is resolved from the DATABASE_URL and cached
for the process lifecycle, and that all dialect-specific functionality
(introspection, DDL, EXPLAIN, engine config, quoting, URL normalization)
works as expected.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openviper.db.dialects import (
    Dialect,
    MariaDBDialect,
    MSSQLDialect,
    OracleDialect,
    PostgreSQLDialect,
    SQLiteDialect,
    get_dialect,
    reset_dialect,
    resolve_dialect,
    resolve_dialect_by_vendor,
)


class TestDriverAvailability:
    """Each dialect must check its driver availability without importing
    unused drivers."""

    def test_sqlite_checks_aiosqlite(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.driver_module == "aiosqlite"
        result = dialect.is_driver_available()
        assert isinstance(result, bool)

    def test_postgres_checks_asyncpg(self) -> None:
        dialect = PostgreSQLDialect()
        assert dialect.driver_module == "asyncpg"
        result = dialect.is_driver_available()
        assert isinstance(result, bool)

    def test_mariadb_checks_aiomysql(self) -> None:
        dialect = MariaDBDialect()
        assert dialect.driver_module == "aiomysql"
        result = dialect.is_driver_available()
        assert isinstance(result, bool)

    def test_mssql_checks_aioodbc(self) -> None:
        dialect = MSSQLDialect()
        assert dialect.driver_module == "aioodbc"
        result = dialect.is_driver_available()
        assert isinstance(result, bool)

    def test_oracle_checks_oracledb(self) -> None:
        dialect = OracleDialect()
        assert dialect.driver_module == "oracledb"
        result = dialect.is_driver_available()
        assert isinstance(result, bool)

    def test_generic_dialect_no_driver_module(self) -> None:
        dialect = Dialect()
        assert dialect.driver_module == ""
        assert dialect.is_driver_available() is True

    def test_driver_available_returns_false_when_module_missing(self) -> None:
        dialect = SQLiteDialect()
        with patch("importlib.util.find_spec", return_value=None):
            assert dialect.is_driver_available() is False


class TestDialectResolution:
    """Dialect resolution from DATABASE_URL with lifecycle caching."""

    def setup_method(self) -> None:
        reset_dialect()

    def teardown_method(self) -> None:
        reset_dialect()

    def test_resolve_sqlite_url(self) -> None:
        dialect = resolve_dialect("sqlite:///db.sqlite3")
        assert isinstance(dialect, SQLiteDialect)

    def test_resolve_postgresql_url(self) -> None:
        dialect = resolve_dialect("postgresql://user:pass@h/db")
        assert isinstance(dialect, PostgreSQLDialect)

    def test_resolve_postgres_short_url(self) -> None:
        dialect = resolve_dialect("postgres://user:pass@h/db")
        assert isinstance(dialect, PostgreSQLDialect)

    def test_resolve_mysql_url(self) -> None:
        dialect = resolve_dialect("mysql://user:pass@h/db")
        assert isinstance(dialect, MariaDBDialect)

    def test_resolve_mariadb_url(self) -> None:
        dialect = resolve_dialect("mariadb://user:pass@h/db")
        assert isinstance(dialect, MariaDBDialect)

    def test_resolve_mssql_url(self) -> None:
        dialect = resolve_dialect("mssql://user:pass@h/db")
        assert isinstance(dialect, MSSQLDialect)

    def test_resolve_oracle_url(self) -> None:
        dialect = resolve_dialect("oracle://user:pass@h/db")
        assert isinstance(dialect, OracleDialect)

    def test_resolve_unknown_url_returns_generic(self) -> None:
        dialect = resolve_dialect("unknown://user:pass@h/db")
        assert type(dialect) is Dialect

    def test_resolve_caches_dialect_for_lifecycle(self) -> None:
        first = resolve_dialect("sqlite:///db.sqlite3")
        second = resolve_dialect("postgresql://h/db")
        assert first is second

    def test_reset_dialect_clears_cache(self) -> None:
        first = resolve_dialect("sqlite:///db.sqlite3")
        reset_dialect()
        second = resolve_dialect("postgresql://h/db")
        assert first is not second

    def test_get_dialect_resolves_from_url_when_not_cached(self) -> None:
        reset_dialect()
        with patch("openviper.conf.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite:///test.sqlite3"
            mock_settings.DATABASES = {}
            dialect = get_dialect()
            assert isinstance(dialect, SQLiteDialect)

    def test_get_dialect_returns_cached_without_re_resolving(self) -> None:
        first = resolve_dialect("sqlite:///db.sqlite3")
        second = get_dialect()
        assert first is second


class TestResolveDialectByVendor:
    """resolve_dialect_by_vendor returns uncached dialect by vendor name."""

    @pytest.mark.parametrize(
        ("vendor", "expected_cls"),
        [
            ("sqlite", SQLiteDialect),
            ("postgresql", PostgreSQLDialect),
            ("mysql", MariaDBDialect),
            ("mssql", MSSQLDialect),
            ("oracle", OracleDialect),
        ],
    )
    def test_known_vendor_returns_dialect(self, vendor: str, expected_cls: type) -> None:
        result = resolve_dialect_by_vendor(vendor)
        assert isinstance(result, expected_cls)

    def test_unknown_vendor_returns_generic(self) -> None:
        result = resolve_dialect_by_vendor("unknown")
        assert type(result) is Dialect

    def test_does_not_cache(self) -> None:
        first = resolve_dialect_by_vendor("sqlite")
        second = resolve_dialect_by_vendor("postgresql")
        assert not isinstance(first, PostgreSQLDialect)
        assert isinstance(second, PostgreSQLDialect)


class TestURLNormalization:
    """Each dialect normalizes sync URLs to async driver equivalents."""

    def test_sqlite_normalizes_to_aiosqlite(self) -> None:
        assert SQLiteDialect().normalize_url("sqlite:///db.sqlite3") == "sqlite+aiosqlite:///db.sqlite3"

    def test_postgresql_normalizes_to_asyncpg(self) -> None:
        assert PostgreSQLDialect().normalize_url("postgresql://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"

    def test_postgres_short_normalizes_to_asyncpg(self) -> None:
        assert PostgreSQLDialect().normalize_url("postgres://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"

    def test_mysql_normalizes_to_aiomysql(self) -> None:
        assert MariaDBDialect().normalize_url("mysql://u:p@h/d") == "mysql+aiomysql://u:p@h/d"

    def test_mariadb_normalizes_to_aiomysql(self) -> None:
        assert MariaDBDialect().normalize_url("mariadb://u:p@h/d") == "mysql+aiomysql://u:p@h/d"

    def test_mssql_normalizes_to_aioodbc(self) -> None:
        assert MSSQLDialect().normalize_url("mssql://u:p@h/d") == "mssql+aioodbc://u:p@h/d"

    def test_oracle_normalizes_to_oracledb_async(self) -> None:
        assert OracleDialect().normalize_url("oracle://u:p@h/d") == "oracle+oracledb_async://u:p@h/d"

    def test_already_async_url_unchanged(self) -> None:
        url = "postgresql+asyncpg://u:p@h/d"
        assert PostgreSQLDialect().normalize_url(url) == url


class TestIdentifierQuoting:
    """Each dialect quotes identifiers differently."""

    def test_sqlite_uses_double_quotes(self) -> None:
        assert SQLiteDialect().quote_identifier("users") == '"users"'

    def test_mysql_uses_backticks(self) -> None:
        assert MariaDBDialect().quote_identifier("users") == "`users`"

    def test_mssql_uses_brackets(self) -> None:
        assert MSSQLDialect().quote_identifier("users") == "[users]"

    def test_oracle_uppercases(self) -> None:
        assert OracleDialect().quote_identifier("users") == "USERS"

    def test_postgresql_uses_double_quotes(self) -> None:
        assert PostgreSQLDialect().quote_identifier("users") == '"users"'


class TestSQLLiterals:
    """Each dialect formats SQL literals differently for booleans."""

    def test_sqlite_true_false(self) -> None:
        d = SQLiteDialect()
        assert d.sql_literal(True) == "TRUE"
        assert d.sql_literal(False) == "FALSE"

    def test_postgresql_true_false(self) -> None:
        d = PostgreSQLDialect()
        assert d.sql_literal(True) == "TRUE"
        assert d.sql_literal(False) == "FALSE"

    def test_mssql_uses_one_zero(self) -> None:
        d = MSSQLDialect()
        assert d.sql_literal(True) == "1"
        assert d.sql_literal(False) == "0"

    def test_oracle_uses_one_zero(self) -> None:
        d = OracleDialect()
        assert d.sql_literal(True) == "1"
        assert d.sql_literal(False) == "0"

    def test_all_dialects_handle_none(self) -> None:
        for cls in [SQLiteDialect, PostgreSQLDialect, MariaDBDialect, MSSQLDialect, OracleDialect]:
            assert cls().sql_literal(None) == "NULL"

    def test_all_dialects_handle_integers(self) -> None:
        for cls in [SQLiteDialect, PostgreSQLDialect, MariaDBDialect, MSSQLDialect, OracleDialect]:
            assert cls().sql_literal(42) == "42"


class TestIntrospectionSQL:
    """Each dialect generates the correct SQL for column introspection."""

    def test_sqlite_pragma(self) -> None:
        sql, params = SQLiteDialect().get_real_columns_sql("users")
        assert "PRAGMA table_info" in sql
        assert params is None

    def test_sqlite_rejects_unsafe_name(self) -> None:
        with pytest.raises(ValueError, match="Unsafe"):
            SQLiteDialect().get_real_columns_sql("users; DROP")

    def test_postgresql_information_schema(self) -> None:
        sql, params = PostgreSQLDialect().get_real_columns_sql("users")
        assert "information_schema.columns" in sql
        assert params == {"tname": "users"}

    def test_mysql_information_schema_with_database(self) -> None:
        sql, params = MariaDBDialect().get_real_columns_sql("users")
        assert "DATABASE()" in sql
        assert params == {"tname": "users"}

    def test_mssql_information_schema_with_db_name(self) -> None:
        sql, _ = MSSQLDialect().get_real_columns_sql("users")
        assert "DB_NAME()" in sql

    def test_oracle_all_tab_columns(self) -> None:
        sql, _ = OracleDialect().get_real_columns_sql("users")
        assert "all_tab_columns" in sql
        assert "UPPER" in sql

    def test_generic_returns_empty(self) -> None:
        sql, params = Dialect().get_real_columns_sql("users")
        assert sql == ""


class TestExplainSyntax:
    """Each dialect generates the correct EXPLAIN syntax."""

    def test_sqlite_query_plan(self) -> None:
        assert "EXPLAIN QUERY PLAN" in SQLiteDialect().explain_sql("SELECT 1")[0]

    def test_postgresql_explain(self) -> None:
        assert PostgreSQLDialect().explain_sql("SELECT 1")[0] == "EXPLAIN SELECT 1"

    def test_mssql_showplan(self) -> None:
        assert "SHOWPLAN_TEXT" in MSSQLDialect().explain_sql("SELECT 1")[0]

    def test_oracle_explain_plan_for(self) -> None:
        assert "EXPLAIN PLAN FOR" in OracleDialect().explain_sql("SELECT 1")[0]


class TestEngineConfiguration:
    """Dialect-specific engine kwargs and configuration."""

    def test_sqlite_memory_returns_static_pool(self) -> None:
        kwargs = SQLiteDialect().get_engine_kwargs("sqlite+aiosqlite:///:memory:", True)
        assert "connect_args" in kwargs
        assert "poolclass" in kwargs

    def test_sqlite_file_returns_empty(self) -> None:
        assert SQLiteDialect().get_engine_kwargs("sqlite+aiosqlite:///db.sqlite3", False) == {}

    def test_mariadb_disables_pool_pre_ping(self) -> None:
        kwargs = MariaDBDialect().get_engine_kwargs("mysql+aiomysql://u:p@h/db", False)
        assert kwargs.get("pool_pre_ping") is False

    def test_generic_returns_empty(self) -> None:
        assert Dialect().get_engine_kwargs("any://url", False) == {}



