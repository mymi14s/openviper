import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    MigrationExecutor,
    MigrationRecord,
    MigrationStatus,
    RemoveColumn,
    RenameColumn,
    RenameTable,
    RestoreColumn,
    RunSQL,
    _count_null_values,
    _count_total_rows,
    _get_dialect,
    _get_existing_columns_sync,
    _get_soft_removed_info,
    _map_column_type,
    _MigrationLogger,
    _normalize_type,
    _quote_identifier,
    _should_skip_backward,
    _should_skip_forward,
    _types_compatible,
    discover_migrations,
    sort_migrations,
    validate_restore_column,
)


class TestMigrationLogger:
    def test_supports_color(self):
        with patch.object(sys.stdout, "isatty", return_value=True):
            assert _MigrationLogger._supports_color() is True
        with patch.object(sys.stdout, "isatty", return_value=False):
            assert _MigrationLogger._supports_color() is False

    def test_colorize(self):
        with patch.object(_MigrationLogger, "_supports_color", return_value=True):
            res = _MigrationLogger._colorize("test", "GREEN")
            assert "\033[92mtest" in res
        with patch.object(_MigrationLogger, "_supports_color", return_value=False):
            res = _MigrationLogger._colorize("test", "GREEN")
            assert res == "test"

    def test_log_methods(self):
        # Just ensure they run without error and call print
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_applying("app", "0001")
            assert mock_print.called

            mock_print.reset_mock()
            _MigrationLogger.log_status(MigrationStatus.OK)
            assert mock_print.called

            mock_print.reset_mock()
            _MigrationLogger.log_summary([("app", "0001", MigrationStatus.OK)])
            assert mock_print.called


class TestDialectHelpers:
    def test_get_dialect_mapping(self):
        with patch("openviper.db.migrations.executor.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql://user:pass@localhost/db"
            _get_dialect.cache_clear()
            assert _get_dialect() == "postgresql"

            mock_settings.DATABASE_URL = "mysql+pymysql://..."
            _get_dialect.cache_clear()
            assert _get_dialect() == "mysql"

            mock_settings.DATABASE_URL = "mssql+pyodbc://..."
            _get_dialect.cache_clear()
            assert _get_dialect() == "mssql"

            mock_settings.DATABASE_URL = "oracle://..."
            _get_dialect.cache_clear()
            assert _get_dialect() == "oracle"

            mock_settings.DATABASE_URL = ""
            _get_dialect.cache_clear()
            assert _get_dialect() == "sqlite"

    def test_map_column_type(self):
        # Base cases
        assert _map_column_type("VARCHAR(100)", "sqlite") == "VARCHAR(100)"
        assert _map_column_type("BOOLEAN", "sqlite") == "INTEGER"

        # Postgres
        assert _map_column_type("JSON", "postgresql") == "JSONB"
        with patch("openviper.db.migrations.executor.settings") as mock_settings:
            mock_settings.USE_TZ = True
            assert _map_column_type("DATETIME", "postgresql") == "TIMESTAMP WITH TIME ZONE"

        # MySQL
        assert _map_column_type("BINARY", "mysql") == "BLOB"

        # Oracle
        assert _map_column_type("BOOLEAN", "oracle") == "NUMBER(1)"

    def test_quote_identifier(self):
        assert _quote_identifier("table", "mysql") == "`table`"
        assert _quote_identifier("table", "mssql") == "[table]"
        assert _quote_identifier("table", "postgresql") == '"table"'


class TestOperations:
    def test_rename_table(self):
        op = RenameTable(old_name="old", new_name="new")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            assert 'ALTER TABLE "old" RENAME TO "new"' in op.forward_sql()[0]
            assert 'ALTER TABLE "new" RENAME TO "old"' in op.backward_sql()[0]

        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            assert "RENAME TABLE `old` TO `new`" in op.forward_sql()[0]

    def test_create_table(self):
        op = CreateTable(
            table_name="users",
            columns=[
                {"name": "id", "type": "INTEGER", "primary_key": True, "autoincrement": True},
                {"name": "name", "type": "VARCHAR(100)", "nullable": False},
            ],
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert 'CREATE TABLE IF NOT EXISTS "users"' in sql
            assert '"id" SERIAL PRIMARY KEY' in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            sql = op.forward_sql()[0]
            assert "AUTOINCREMENT" in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            sql = op.forward_sql()[0]
            assert "AUTO_INCREMENT" in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="oracle"):
            sql = op.forward_sql()[0]
            assert "GENERATED BY DEFAULT AS IDENTITY" in sql

    def test_add_column(self):
        op = AddColumn(table_name="t", column_name="c", column_type="INTEGER", nullable=False)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert 'ALTER TABLE "t" ADD COLUMN "c" INTEGER NOT NULL' in sql

    def test_remove_column_soft(self):
        op = RemoveColumn(table_name="t", column_name="c")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql_objs = op.forward_sql()
            assert len(sql_objs) == 1
            # It should be a sa.text object
            assert 'INSERT INTO "openviper_soft_removed_columns"' in sql_objs[0].text

    def test_alter_column(self):
        op = AlterColumn(
            table_name="t", column_name="c", column_type="VARCHAR(200)", old_type="VARCHAR(100)"
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert "TYPE VARCHAR(200)" in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            sql = op.forward_sql()[0]
            assert "MODIFY COLUMN `c` VARCHAR(200)" in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="oracle"):
            sql = op.forward_sql()[0]
            assert 'MODIFY "c" VARCHAR2(200)' in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.forward_sql()[0]
            assert "ALTER COLUMN [c] VARCHAR(200)" in sql

        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            sql = op.forward_sql()[0]
            assert 'ALTER COLUMN "c" TYPE VARCHAR(200)' in sql

    def test_alter_column_details(self):
        # Test type and nullability changes for postgres
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(200)",
            nullable=False,
            old_type="VARCHAR(100)",
            old_nullable=True,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql_list = op.forward_sql()
            assert any("TYPE VARCHAR(200)" in s for s in sql_list)
            assert any("SET NOT NULL" in s for s in sql_list)

            back_list = op.backward_sql()
            assert any("TYPE VARCHAR(100)" in s for s in back_list)
            assert any("DROP NOT NULL" in s for s in back_list)

    def test_run_sql(self):
        op = RunSQL(sql="SELECT 1", reverse_sql="SELECT 2")
        assert op.forward_sql() == ["SELECT 1"]
        assert op.backward_sql() == ["SELECT 2"]

    def test_drop_table(self):
        op = DropTable(table_name="t")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            assert 'DROP TABLE IF EXISTS "t"' in op.forward_sql()[0]
            assert op.backward_sql() == []

    def test_rename_column(self):
        op = RenameColumn(table_name="t", old_name="old", new_name="new")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            assert 'RENAME COLUMN "old" TO "new"' in op.forward_sql()[0]
            assert 'RENAME COLUMN "new" TO "old"' in op.backward_sql()[0]

    def test_create_index(self):
        op = CreateIndex(table_name="t", index_name="idx", columns=["c1", "c2"], unique=True)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert 'CREATE UNIQUE INDEX IF NOT EXISTS "idx" ON "t" ("c1", "c2")' in sql

    def test_restore_column(self):
        op = RestoreColumn(table_name="t", column_name="c")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql_objs = op.forward_sql()
            assert 'DELETE FROM "openviper_soft_removed_columns"' in sql_objs[0].text
            back_objs = op.backward_sql()
            assert 'INSERT INTO "openviper_soft_removed_columns"' in back_objs[0].text


class TestMigrationDiscovery:
    def test_sort_migrations(self):
        m1 = MigrationRecord(app="app1", name="0001", dependencies=[], operations=[], path="")
        m2 = MigrationRecord(
            app="app1", name="0002", dependencies=[("app1", "0001")], operations=[], path=""
        )
        m3 = MigrationRecord(
            app="app2", name="0001", dependencies=[("app1", "0002")], operations=[], path=""
        )

        # Reverse order to see if it sorts
        sorted_list = sort_migrations([m3, m2, m1])
        assert sorted_list == [m1, m2, m3]

    def test_sort_migrations_circular(self):
        m1 = MigrationRecord(
            app="app1", name="0001", dependencies=[("app1", "0002")], operations=[], path=""
        )
        m2 = MigrationRecord(
            app="app1", name="0002", dependencies=[("app1", "0001")], operations=[], path=""
        )

        with patch("openviper.db.migrations.executor.logger") as mock_logger:
            sorted_list = sort_migrations([m1, m2])
            assert mock_logger.warning.called
            assert len(sorted_list) == 2

    def test_discover_migrations_legacy_path(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob", return_value=[Path("apps/myapp/migrations/0001_initial.py")]
            ),
            patch("importlib.util.spec_from_file_location") as mock_spec,
        ):
            mock_spec.return_value.loader.exec_module = MagicMock()

            # Simple test to see if it calls the dir walker
            with patch(
                "openviper.db.migrations.executor._discover_app_migrations"
            ) as mock_discover:
                discover_migrations(apps_dir="apps")
                assert mock_discover.called


class TestMigrationExecutor:
    @pytest.mark.asyncio
    async def test_ensure_migration_table(self):
        ex = MigrationExecutor()
        with patch(
            "openviper.db.migrations.executor.get_engine", new_callable=AsyncMock
        ) as mock_get_engine:
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine

            # Mock engine.begin() as an async context manager
            mock_conn = AsyncMock()
            mock_engine.begin.return_value.__aenter__.return_value = mock_conn

            await ex._ensure_migration_table()
            assert mock_get_engine.called

    @pytest.mark.asyncio
    async def test_applied_migrations(self):
        ex = MigrationExecutor()
        with patch(
            "openviper.db.migrations.executor.get_engine", new_callable=AsyncMock
        ) as mock_get_engine:
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine

            # Mock engine.connect() as an async context manager
            mock_conn = AsyncMock()
            mock_engine.connect.return_value.__aenter__.return_value = mock_conn

            # Mock the result of conn.execute
            mock_result = MagicMock()
            row = MagicMock()
            row.app = "app1"
            row.name = "0001"
            mock_result.__iter__.return_value = [row]
            mock_conn.execute.return_value = mock_result

            applied = await ex._applied_migrations()
            assert ("app1", "0001") in applied

    @pytest.mark.asyncio
    async def test_migrate_no_pending(self):
        ex = MigrationExecutor()
        with (
            patch("openviper.db.migrations.executor.get_engine", new_callable=AsyncMock),
            patch.object(ex, "_ensure_migration_table", new_callable=AsyncMock),
            patch.object(ex, "_applied_migrations", new_callable=AsyncMock) as mock_applied,
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[]),
        ):
            mock_applied.return_value = set()
            applied = await ex.migrate(verbose=False)
            assert applied == []

    @pytest.mark.asyncio
    async def test_rollback_basic(self):
        ex = MigrationExecutor()
        m1 = MigrationRecord(
            app="app1", name="0001", dependencies=[], operations=[RunSQL("SELECT 1")], path=""
        )
        with (
            patch(
                "openviper.db.migrations.executor.get_engine", new_callable=AsyncMock
            ) as mock_get_engine,
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[m1]),
        ):
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine
            mock_conn = AsyncMock()
            mock_engine.begin.return_value.__aenter__.return_value = mock_conn

            await ex.rollback("app1", "0001")
            assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_migrate_failure(self):
        ex = MigrationExecutor()
        m1 = MigrationRecord(
            app="app1", name="0001", dependencies=[], operations=[RunSQL("FAIL")], path=""
        )
        with (
            patch.object(ex, "_ensure_migration_table", new_callable=AsyncMock),
            patch.object(ex, "_applied_migrations", return_value=set(), new_callable=AsyncMock),
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[m1]),
            patch(
                "openviper.db.migrations.executor.get_engine", new_callable=AsyncMock
            ) as mock_get_engine,
        ):
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine
            mock_conn = AsyncMock()
            mock_engine.begin.return_value.__aenter__.return_value = mock_conn
            mock_conn.execute.side_effect = Exception("DB Error")

            with pytest.raises(Exception, match="DB Error"):
                await ex.migrate(verbose=False)


class TestMigrationIntrospection:
    @pytest.mark.asyncio
    async def test_should_skip_forward_add_column(self):
        conn = MagicMock()
        # Mocking _column_exists to return True
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            op = AddColumn(table_name="t", column_name="c", column_type="TEXT")
            assert await _should_skip_forward(conn, op) is True

    @pytest.mark.asyncio
    async def test_should_skip_backward_add_column_not_exists(self):
        conn = MagicMock()
        # Mocking _column_exists to return False
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=False,
        ):
            op = AddColumn(table_name="t", column_name="c", column_type="TEXT")
            assert await _should_skip_backward(conn, op) is True


class TestMigrationValidation:
    @pytest.mark.asyncio
    async def test_validate_restore_column_type_mismatch(self):
        op = RestoreColumn(table_name="t", column_name="c")
        conn = AsyncMock()
        soft_info = {"column_type": "INTEGER"}

        with patch(
            "openviper.db.migrations.executor._get_soft_removed_info", return_value=soft_info
        ):
            error = await validate_restore_column(conn, op, new_type="TEXT", new_nullable=True)
            assert "type mismatch" in error

    @pytest.mark.asyncio
    async def test_validate_restore_column_null_conflict(self):
        op = RestoreColumn(table_name="t", column_name="c")
        conn = AsyncMock()
        soft_info = {"column_type": "TEXT"}

        with (
            patch(
                "openviper.db.migrations.executor._get_soft_removed_info", return_value=soft_info
            ),
            patch("openviper.db.migrations.executor._count_null_values", return_value=5),
        ):
            error = await validate_restore_column(conn, op, new_type="TEXT", new_nullable=False)
            assert "rows have NULL values" in error


class TestMigrationLoggerBranches:
    def test_log_status_skip(self):
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_status(MigrationStatus.SKIP)
            mock_print.assert_called_once()
            assert "SKIP" in mock_print.call_args[0][0]

    def test_log_status_error_without_msg(self):
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_status(MigrationStatus.ERROR)
            mock_print.assert_called_once()
            assert "ERROR" in mock_print.call_args[0][0]

    def test_log_status_error_with_msg(self):
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_status(MigrationStatus.ERROR, error="something broke")
            assert mock_print.call_count == 2
            assert "ERROR" in mock_print.call_args_list[0][0][0]
            assert "something broke" in mock_print.call_args_list[1][0][0]

    def test_log_status_rollback(self):
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_status(MigrationStatus.ROLLBACK)
            mock_print.assert_called_once()
            assert "ROLLBACK" in mock_print.call_args[0][0]

    def test_log_status_pending(self):
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_status(MigrationStatus.PENDING)
            mock_print.assert_called_once()
            assert "PENDING" in mock_print.call_args[0][0]

    def test_log_summary_with_errors(self):
        migrations_list = [
            ("app1", "0001", MigrationStatus.OK),
            ("app1", "0002", MigrationStatus.ERROR),
        ]
        with patch("builtins.print") as mock_print:
            _MigrationLogger.log_summary(migrations_list)
            output = " ".join(str(c) for c in mock_print.call_args_list)
            assert "failed" in output.lower() or "ERROR" in output


class TestRenameTableMssql:
    def test_forward_sql_mssql(self):
        op = RenameTable(old_name="old", new_name="new")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.forward_sql()
            assert len(sql) == 1
            assert "EXEC sp_rename" in sql[0]
            assert "N'old'" in sql[0]
            assert "N'new'" in sql[0]
            assert "'OBJECT'" in sql[0]

    def test_backward_sql_mssql(self):
        op = RenameTable(old_name="old", new_name="new")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.backward_sql()
            assert len(sql) == 1
            assert "EXEC sp_rename" in sql[0]
            assert "N'new'" in sql[0]
            assert "N'old'" in sql[0]
            assert "'OBJECT'" in sql[0]


class TestCreateTableExtended:
    def test_mssql_identity(self):
        op = CreateTable(
            table_name="t",
            columns=[
                {"name": "id", "type": "INTEGER", "primary_key": True, "autoincrement": True},
            ],
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.forward_sql()[0]
            assert "IDENTITY(1,1)" in sql

    def test_fk_support(self):
        op = CreateTable(
            table_name="posts",
            columns=[
                {"name": "id", "type": "INTEGER", "primary_key": True, "autoincrement": True},
                {
                    "name": "author_id",
                    "type": "INTEGER",
                    "nullable": False,
                    "target_table": "users",
                    "on_delete": "CASCADE",
                },
            ],
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert 'REFERENCES "users"(id) ON DELETE CASCADE' in sql


class TestAddColumnExtended:
    def test_with_default_value(self):
        op = AddColumn(table_name="t", column_name="c", column_type="INTEGER", default=42)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert "DEFAULT 42" in sql

    def test_backward_sql(self):
        op = AddColumn(table_name="t", column_name="c", column_type="INTEGER")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.backward_sql()
            assert len(sql) == 1
            assert 'DROP COLUMN "c"' in sql[0]


class TestRemoveColumnExtended:
    def test_drop_true_forward(self):
        op = RemoveColumn(table_name="t", column_name="c", drop=True)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()
            assert len(sql) == 1
            assert 'DROP COLUMN "c"' in sql[0]

    def test_backward_sql_drop_true(self):
        op = RemoveColumn(table_name="t", column_name="c", column_type="INTEGER", drop=True)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.backward_sql()
            assert len(sql) == 1
            assert 'ADD COLUMN "c" INTEGER' in sql[0]

    def test_backward_sql_soft_remove(self):
        op = RemoveColumn(table_name="t", column_name="c")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql_objs = op.backward_sql()
            assert len(sql_objs) == 1
            assert "DELETE FROM" in sql_objs[0].text
            assert "openviper_soft_removed_columns" in sql_objs[0].text


class TestAlterColumnExtended:
    def test_nullable_mysql(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(100)",
            nullable=False,
            old_type="VARCHAR(100)",
            old_nullable=True,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            stmts = op.forward_sql()
            assert any("MODIFY COLUMN" in s and "NOT NULL" in s for s in stmts)

    def test_nullable_mssql(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(100)",
            nullable=False,
            old_type="VARCHAR(100)",
            old_nullable=True,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            stmts = op.forward_sql()
            assert any("ALTER COLUMN [c]" in s and "NOT NULL" in s for s in stmts)

    def test_nullable_oracle(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(100)",
            nullable=True,
            old_type="VARCHAR(100)",
            old_nullable=False,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="oracle"):
            stmts = op.forward_sql()
            assert any("MODIFY" in s and "NULL" in s for s in stmts)

    def test_default_postgresql(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="TEXT",
            default="hello",
            old_type="TEXT",
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            stmts = op.forward_sql()
            assert any("SET DEFAULT" in s and "'hello'" in s for s in stmts)

    def test_default_mysql(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="TEXT",
            default="world",
            old_type="TEXT",
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            stmts = op.forward_sql()
            assert any("SET DEFAULT" in s for s in stmts)

    def test_backward_sql_type_and_nullable(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(200)",
            nullable=False,
            old_type="VARCHAR(100)",
            old_nullable=True,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            stmts = op.backward_sql()
            assert any("TYPE VARCHAR(100)" in s for s in stmts)
            assert any("DROP NOT NULL" in s for s in stmts)

    def test_backward_sql_old_default(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="TEXT",
            default="new_val",
            old_type="TEXT",
            old_default="old_val",
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            stmts = op.backward_sql()
            assert any("SET DEFAULT" in s and "'old_val'" in s for s in stmts)

    def test_backward_sql_set_not_null(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="TEXT",
            nullable=True,
            old_type="TEXT",
            old_nullable=False,
        )
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            stmts = op.backward_sql()
            assert any("SET NOT NULL" in s for s in stmts)


class TestRenameColumnMssql:
    def test_forward_sql_mssql(self):
        op = RenameColumn(table_name="t", old_name="old_col", new_name="new_col")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.forward_sql()
            assert len(sql) == 1
            assert "EXEC sp_rename" in sql[0]
            assert "t.old_col" in sql[0]
            assert "'new_col'" in sql[0]
            assert "'COLUMN'" in sql[0]

    def test_backward_sql_mssql(self):
        op = RenameColumn(table_name="t", old_name="old_col", new_name="new_col")
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            sql = op.backward_sql()
            assert len(sql) == 1
            assert "EXEC sp_rename" in sql[0]
            assert "t.new_col" in sql[0]
            assert "'old_col'" in sql[0]


class TestCreateIndexExtended:
    def test_backward_sql(self):
        op = CreateIndex(table_name="t", index_name="idx", columns=["c1"], unique=True)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.backward_sql()
            assert len(sql) == 1
            assert 'DROP INDEX IF EXISTS "idx"' in sql[0]

    def test_non_unique_index(self):
        op = CreateIndex(table_name="t", index_name="idx", columns=["c1"], unique=False)
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            sql = op.forward_sql()[0]
            assert "UNIQUE" not in sql
            assert "CREATE INDEX IF NOT EXISTS" in sql


class TestRunSQLExtended:
    def test_backward_sql_empty_reverse(self):
        op = RunSQL(sql="SELECT 1")
        assert op.backward_sql() == []


class TestShouldSkipForwardRemoveColumn:
    @pytest.mark.asyncio
    async def test_skip_remove_column_not_exists(self):
        conn = MagicMock()
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=False,
        ):
            op = RemoveColumn(table_name="t", column_name="c")
            assert await _should_skip_forward(conn, op) is True

    @pytest.mark.asyncio
    async def test_no_skip_remove_column_exists(self):
        conn = MagicMock()
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            op = RemoveColumn(table_name="t", column_name="c")
            assert await _should_skip_forward(conn, op) is False


class TestNormalizeTypeAndTypesCompatible:
    def test_normalize_type_strips_parens(self):
        assert _normalize_type("VARCHAR(255)") == "VARCHAR"
        assert _normalize_type("INTEGER") == "INTEGER"

    def test_normalize_type_aliases(self):
        assert _normalize_type("INT") == "INTEGER"
        assert _normalize_type("BOOL") == "BOOLEAN"
        assert _normalize_type("FLOAT") == "REAL"
        assert _normalize_type("DOUBLE") == "REAL"
        assert _normalize_type("STRING") == "VARCHAR"
        assert _normalize_type("CHAR") == "VARCHAR"

    def test_types_compatible_same(self):
        assert _types_compatible("VARCHAR(100)", "VARCHAR(255)") is True
        assert _types_compatible("INT", "INTEGER") is True

    def test_types_incompatible(self):
        assert _types_compatible("TEXT", "INTEGER") is False
        assert _types_compatible("BOOLEAN", "VARCHAR(50)") is False


class TestGetDialectBranches:
    def test_dialect_exception_returns_sqlite(self):
        """Settings access raises, returns default sqlite."""
        _get_dialect.cache_clear()
        try:
            with patch("openviper.db.migrations.executor.settings") as mock_settings:
                type(mock_settings).DATABASE_URL = property(
                    lambda self: (_ for _ in ()).throw(RuntimeError("broken"))
                )
                result = _get_dialect()
                assert result == "sqlite"
        finally:
            _get_dialect.cache_clear()

    def test_dialect_oracle(self):
        """Oracle dialect detection."""
        _get_dialect.cache_clear()
        try:
            with patch("openviper.db.migrations.executor.settings") as mock_settings:
                mock_settings.DATABASE_URL = "oracle://user:pass@host/db"
                result = _get_dialect()
                assert result == "oracle"
        finally:
            _get_dialect.cache_clear()


class TestMapColumnTypeTZBranch:
    def test_datetime_with_use_tz_postgres(self):
        """DATETIME → TIMESTAMP WITH TIME ZONE when USE_TZ is enabled."""
        with patch("openviper.db.migrations.executor.settings") as mock_settings:
            mock_settings.USE_TZ = True
            result = _map_column_type("DATETIME", "postgresql")
            assert "TIMESTAMP WITH TIME ZONE" in result

    def test_datetime_without_use_tz_postgres(self):
        with patch("openviper.db.migrations.executor.settings") as mock_settings:
            mock_settings.USE_TZ = False
            result = _map_column_type("DATETIME", "postgresql")
            assert result == "TIMESTAMP"


class TestCreateTableColumnBranches:
    def test_autoincrement_mssql(self):
        """MSSQL uses IDENTITY for autoincrement columns."""
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            op = CreateTable(
                table_name="test_t",
                columns=[
                    {"name": "id", "type": "INTEGER", "primary_key": True, "autoincrement": True}
                ],
            )
            sql = op.forward_sql()[0]
            assert "IDENTITY" in sql

    def test_autoincrement_oracle(self):
        """Oracle uses GENERATED BY DEFAULT AS IDENTITY for autoincrement."""
        with patch("openviper.db.migrations.executor._get_dialect", return_value="oracle"):
            op = CreateTable(
                table_name="test_t",
                columns=[
                    {"name": "id", "type": "INTEGER", "primary_key": True, "autoincrement": True}
                ],
            )
            sql = op.forward_sql()[0]
            assert "GENERATED BY DEFAULT AS IDENTITY" in sql

    def test_column_with_fk_reference(self):
        """FK foreign reference in column definition."""
        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            op = CreateTable(
                table_name="comments",
                columns=[
                    {"name": "id", "type": "INTEGER", "primary_key": True},
                    {
                        "name": "post_id",
                        "type": "INTEGER",
                        "target_table": "posts",
                        "on_delete": "SET NULL",
                    },
                ],
            )
            sql = op.forward_sql()[0]
            assert 'REFERENCES "posts"(id) ON DELETE SET NULL' in sql

    def test_column_unique_and_default(self):
        """Unique constraint and default value in column definition."""
        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            op = CreateTable(
                table_name="test_t",
                columns=[
                    {
                        "name": "code",
                        "type": "VARCHAR(10)",
                        "unique": True,
                        "default": "ABC",
                        "nullable": False,
                    },
                ],
            )
            sql = op.forward_sql()[0]
            assert "UNIQUE" in sql
            assert "DEFAULT" in sql
            assert "NOT NULL" in sql


class TestDiscoverMigrationsResolved:
    def test_discover_with_resolved_apps(self, tmp_path):
        """Discover migrations using resolved_apps dictionary."""
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        mig_dir = app_dir / "migrations"
        mig_dir.mkdir()
        # Create a simple migration file
        mig_file = mig_dir / "0001_initial.py"
        mig_file.write_text("dependencies = []\noperations = []\n")
        with patch("openviper.db.migrations.executor._BUILTIN_APP_PACKAGES", []):
            records = discover_migrations(resolved_apps={"myapp": str(app_dir)})
            assert any(r.app == "myapp" for r in records)

    def test_discover_with_apps_dir_legacy(self, tmp_path):
        """Discover migrations using legacy apps_dir path."""
        app_dir = tmp_path / "blog"
        app_dir.mkdir()
        mig_dir = app_dir / "migrations"
        mig_dir.mkdir()
        mig_file = mig_dir / "0001_init.py"
        mig_file.write_text("dependencies = []\noperations = []\n")
        with patch("openviper.db.migrations.executor._BUILTIN_APP_PACKAGES", []):
            records = discover_migrations(apps_dir=str(tmp_path))
            assert any(r.app == "blog" for r in records)


class TestMigrationExecutorMigrate:
    @pytest.mark.asyncio
    async def test_migrate_applies_operations(self):
        """Migration apply path with verbose logging."""

        executor = MigrationExecutor()
        record = MigrationRecord(
            app="test", name="0001_initial", dependencies=[], operations=[], path=""
        )

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            yield mock_conn

        mock_engine = AsyncMock()
        mock_engine.begin = fake_begin

        with (
            patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
            patch.object(
                executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()
            ),
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[record]),
            patch(
                "openviper.db.migrations.executor.get_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("openviper.db.migrations.executor._get_migration_table"),
            patch("openviper.db.migrations.executor.sa"),
            patch("openviper.db.migrations.executor.settings") as mock_settings,
            patch("openviper.db.migrations.executor.timezone") as mock_tz,
        ):
            mock_settings.USE_TZ = False
            mock_settings.INSTALLED_APPS = []
            mock_tz.now.return_value = MagicMock(replace=MagicMock(return_value="2024-01-01"))
            result = await executor.migrate(verbose=False)
            assert "0001_initial" in result

    @pytest.mark.asyncio
    async def test_migrate_skips_applied(self):
        """Already applied migrations are skipped."""
        executor = MigrationExecutor()
        record = MigrationRecord(
            app="test", name="0001_initial", dependencies=[], operations=[], path=""
        )
        with (
            patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
            patch.object(
                executor,
                "_applied_migrations",
                new_callable=AsyncMock,
                return_value={("test", "0001_initial")},
            ),
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[record]),
            patch("openviper.db.migrations.executor.get_engine", new_callable=AsyncMock),
            patch("openviper.db.migrations.executor._get_migration_table"),
            patch("openviper.db.migrations.executor.settings") as mock_settings,
        ):
            mock_settings.INSTALLED_APPS = []
            result = await executor.migrate(verbose=False)
            assert result == []

    @pytest.mark.asyncio
    async def test_migrate_error_with_ignore(self):
        """Error with ignore_errors=True allows migration to continue."""

        executor = MigrationExecutor()
        bad_op = RunSQL(sql="INVALID SQL")
        record = MigrationRecord(
            app="test", name="0001_bad", dependencies=[], operations=[bad_op], path=""
        )

        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = RuntimeError("SQL error")

        @asynccontextmanager
        async def fake_begin():
            yield mock_conn

        mock_engine = AsyncMock()
        mock_engine.begin = fake_begin

        with (
            patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
            patch.object(
                executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()
            ),
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[record]),
            patch(
                "openviper.db.migrations.executor.get_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("openviper.db.migrations.executor._get_migration_table"),
            patch("openviper.db.migrations.executor.settings") as mock_settings,
        ):
            mock_settings.INSTALLED_APPS = []
            result = await executor.migrate(verbose=False, ignore_errors=True)
            assert result == []


class TestValidateRestoreColumn:
    @pytest.mark.asyncio
    async def test_validate_no_soft_info(self):
        """Validate when column is not soft-removed."""
        conn = AsyncMock()
        with patch(
            "openviper.db.migrations.executor._get_soft_removed_info",
            new_callable=AsyncMock,
            return_value=None,
        ):
            op = RestoreColumn(table_name="t", column_name="c")
            result = await validate_restore_column(conn, op, new_type="TEXT", new_nullable=True)
            assert result is None

    @pytest.mark.asyncio
    async def test_validate_type_mismatch(self):
        """Type mismatch error when restoring column."""
        conn = AsyncMock()
        soft_info = {"table_name": "t", "column_name": "c", "column_type": "INTEGER"}
        with patch(
            "openviper.db.migrations.executor._get_soft_removed_info",
            new_callable=AsyncMock,
            return_value=soft_info,
        ):
            op = RestoreColumn(table_name="t", column_name="c")
            result = await validate_restore_column(conn, op, new_type="TEXT", new_nullable=True)
            assert result is not None
            assert "type mismatch" in result.lower()

    @pytest.mark.asyncio
    async def test_validate_null_values(self):
        """Null values prevent NOT NULL restoration."""
        conn = AsyncMock()
        soft_info = {"table_name": "t", "column_name": "c", "column_type": "TEXT"}
        with (
            patch(
                "openviper.db.migrations.executor._get_soft_removed_info",
                new_callable=AsyncMock,
                return_value=soft_info,
            ),
            patch(
                "openviper.db.migrations.executor._count_null_values",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "openviper.db.migrations.executor._count_total_rows",
                new_callable=AsyncMock,
                return_value=10,
            ),
        ):
            op = RestoreColumn(table_name="t", column_name="c")
            result = await validate_restore_column(conn, op, new_type="TEXT", new_nullable=False)
            assert result is not None
            assert "NULL" in result


class TestShouldSkipBackward:
    @pytest.mark.asyncio
    async def test_skip_backward_add_column_not_exists(self):
        """Skip backward DROP when column doesn't exist."""
        conn = AsyncMock()
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=False,
        ):
            assert (
                await _should_skip_backward(
                    conn, AddColumn(table_name="t", column_name="c", column_type="TEXT")
                )
                is True
            )

    @pytest.mark.asyncio
    async def test_no_skip_backward_add_column_exists(self):
        conn = AsyncMock()
        with patch(
            "openviper.db.migrations.executor._column_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            assert (
                await _should_skip_backward(
                    conn, AddColumn(table_name="t", column_name="c", column_type="TEXT")
                )
                is False
            )

    @pytest.mark.asyncio
    async def test_no_skip_backward_other_op(self):
        conn = AsyncMock()
        assert await _should_skip_backward(conn, DropTable(table_name="t")) is False


# ── Coverage for _get_soft_removed_info and _count helpers (L862-866, 905-926)


class TestSoftRemovedHelpers:
    @pytest.mark.asyncio
    async def test_get_soft_removed_info_returns_none_on_exception(self):
        conn = AsyncMock()
        with patch(
            "openviper.db.migrations.executor._get_soft_removed_table",
            side_effect=RuntimeError("boom"),
        ):
            result = await _get_soft_removed_info(conn, "t", "c")
            assert result is None

    @pytest.mark.asyncio
    async def test_count_null_values_exception(self):
        conn = AsyncMock()
        conn.execute.side_effect = RuntimeError("boom")
        result = await _count_null_values(conn, "t", "c")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_total_rows_exception(self):
        conn = AsyncMock()
        conn.execute.side_effect = RuntimeError("boom")
        result = await _count_total_rows(conn, "t")
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_existing_columns_exception(self):
        conn = MagicMock()
        with patch("openviper.db.migrations.executor.sa.inspect", side_effect=RuntimeError("boom")):
            result = _get_existing_columns_sync(conn, "nonexistent")
            assert result == set()


class TestMigrationExecutorRollback:
    @pytest.mark.asyncio
    async def test_rollback_not_found_raises(self):
        executor = MigrationExecutor()
        mock_engine = AsyncMock()
        with (
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[]),
            patch(
                "openviper.db.migrations.executor.get_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("openviper.db.migrations.executor._get_migration_table"),
        ):
            with pytest.raises(ValueError, match="not found"):
                await executor.rollback("myapp", "0099_nonexistent")

    @pytest.mark.asyncio
    async def test_rollback_success(self):

        executor = MigrationExecutor()
        record = MigrationRecord(
            app="test", name="0001_initial", dependencies=[], operations=[], path=""
        )
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            yield mock_conn

        mock_engine = AsyncMock()
        mock_engine.begin = fake_begin

        with (
            patch("openviper.db.migrations.executor.discover_migrations", return_value=[record]),
            patch(
                "openviper.db.migrations.executor.get_engine",
                new_callable=AsyncMock,
                return_value=mock_engine,
            ),
            patch("openviper.db.migrations.executor._get_migration_table") as mock_table,
            patch("openviper.db.migrations.executor.sa"),
        ):
            mock_table.return_value = MagicMock()
            await executor.rollback("test", "0001_initial")


class TestMigrationLoggerExtended:
    def test_log_summary(self, capsys):
        log = [
            ("app1", "0001_init", MigrationStatus.OK),
            ("app1", "0002_add", MigrationStatus.ERROR),
            ("app2", "0001_init", MigrationStatus.SKIP),
        ]
        _MigrationLogger.log_summary(log)
        captured = capsys.readouterr()
        assert "OK" in captured.out or "Summary" in captured.out or "app1" in captured.out

    def test_log_applying(self, capsys):
        _MigrationLogger.log_applying("myapp", "0001_initial")
        captured = capsys.readouterr()
        assert "myapp" in captured.out or "0001" in captured.out
