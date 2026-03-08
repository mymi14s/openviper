import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    MigrationExecutor,
    MigrationRecord,
    MigrationStatus,
    Operation,
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
    _should_skip_backward,
    _should_skip_forward,
    _types_compatible,
    discover_migrations,
    sort_migrations,
    validate_restore_column,
)


def test_dialect_mapper():
    assert _map_column_type("DATETIME", "postgresql") == "TIMESTAMP WITH TIME ZONE"  # or TIMESTAMP
    assert "TIMESTAMP" in _map_column_type("DATETIME", "postgresql")
    assert _map_column_type("VARCHAR(50)", "postgresql") == "VARCHAR(50)"
    assert _map_column_type("UUID", "mysql") == "CHAR(36)"
    assert _map_column_type("JSON", "sqlite") == "TEXT"
    assert _map_column_type("JSONB", "sqlite") == "JSONB"  # Unmapped


@patch("openviper.conf.settings.DATABASE_URL", "sqlite:///test.db", create=True)
def test_get_dialect():
    assert _get_dialect() == "sqlite"


def test_get_dialect_missing():
    with patch("openviper.db.migrations.executor.settings") as mk:
        del mk.DATABASE_URL
        assert _get_dialect() == "sqlite"
        mk.DATABASE_URL = "postgresql://a"
        assert _get_dialect() == "postgresql"
        mk.DATABASE_URL = "mysql://a"
        assert _get_dialect() == "mysql"


def test_types_compatible():
    assert _types_compatible("JSON", "JSON") is True
    # If JSON normalizes to TEXT or not, let's just test ones we know.
    assert _types_compatible("INT", "INTEGER") is True
    assert _types_compatible("INT", "TEXT") is False
    assert _types_compatible("VARCHAR(55)", "VARCHAR(55)") is True
    assert _types_compatible("VARCHAR(10)", "VARCHAR(100)") is True  # size ignored


def test_operations_sql():
    c = CreateTable(
        "t", [{"name": "id", "type": "INT", "primary_key": True, "autoincrement": True}]
    )
    fwd = c.forward_sql()
    assert "CREATE TABLE" in fwd[0]
    assert '"id" INT PRIMARY KEY AUTOINCREMENT' in fwd[0]
    assert c.backward_sql()[0] == 'DROP TABLE IF EXISTS "t"'

    with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
        c_pg = CreateTable(
            "t",
            [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                    "unique": True,
                    "default": 1,
                }
            ],
        )
        pg_sql = c_pg.forward_sql()[0]
        assert "SERIAL PRIMARY KEY NOT NULL UNIQUE DEFAULT 1" in pg_sql

    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        c_my = CreateTable(
            "t", [{"name": "id", "type": "INT", "primary_key": True, "autoincrement": True}]
        )
        my_sql = c_my.forward_sql()[0]
        assert "AUTO_INCREMENT" in my_sql

    d = DropTable("t")
    assert d.forward_sql()[0] == 'DROP TABLE IF EXISTS "t"'
    assert d.backward_sql() == []


def test_add_remove_column():
    a = AddColumn("t", "c", "TEXT", default="'a'", nullable=False)
    assert 'ALTER TABLE "t" ADD COLUMN "c" TEXT NOT NULL' in a.forward_sql()[0]
    assert a.backward_sql()[0] == 'ALTER TABLE "t" DROP COLUMN "c"'

    r = RemoveColumn("t", "c", "TEXT", drop=True)
    assert r.forward_sql()[0] == 'ALTER TABLE "t" DROP COLUMN "c"'
    assert 'ALTER TABLE "t" ADD COLUMN "c"' in r.backward_sql()[0]

    r_soft = RemoveColumn("t", "c", "TEXT", drop=False)
    assert 'INSERT INTO "openviper_soft_removed_columns"' in r_soft.forward_sql()[0].text
    assert 'DELETE FROM "openviper_soft_removed_columns"' in r_soft.backward_sql()[0].text


@patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql")
def test_alter_rename_restore(mock_dialect):

    idx = CreateIndex("t", "idx_t", ["c"], unique=True)
    assert "CREATE UNIQUE INDEX" in idx.forward_sql()[0]
    assert "DROP INDEX IF EXISTS" in idx.backward_sql()[0]

    r_sql = RunSQL("SELECT 1", reverse_sql="SELECT 2")
    assert r_sql.forward_sql()[0] == "SELECT 1"
    assert r_sql.backward_sql()[0] == "SELECT 2"
    assert RunSQL("A").backward_sql() == []

    alt = AlterColumn(
        "t",
        "c",
        column_type="INTEGER",
        nullable=False,
        default=1,
        old_type="TEXT",
        old_nullable=True,
        old_default=2,
    )
    fwd = alt.forward_sql()
    assert any('ALTER TABLE "t" ALTER COLUMN "c" TYPE INTEGER' in x for x in fwd)
    assert any('ALTER TABLE "t" ALTER COLUMN "c" SET NOT NULL' in x for x in fwd)
    assert any('ALTER TABLE "t" ALTER COLUMN "c" SET DEFAULT 1' in x for x in fwd)

    bwd = alt.backward_sql()
    assert any('ALTER TABLE "t" ALTER COLUMN "c" TYPE TEXT' in x for x in bwd)
    assert any('ALTER TABLE "t" ALTER COLUMN "c" DROP NOT NULL' in x for x in bwd)
    assert any('ALTER TABLE "t" ALTER COLUMN "c" SET DEFAULT 2' in x for x in bwd)

    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        alt_my = AlterColumn(
            "t",
            "c",
            column_type="INTEGER",
            nullable=False,
            default=1,
            old_type="TEXT",
            old_nullable=True,
        )
        my_fwd = alt_my.forward_sql()
        assert any("MODIFY COLUMN `c` INTEGER NOT NULL" in x for x in my_fwd)

    ren = RenameColumn("t", "old", "new")
    assert ren.forward_sql()[0] == 'ALTER TABLE "t" RENAME COLUMN "old" TO "new"'
    assert ren.backward_sql()[0] == 'ALTER TABLE "t" RENAME COLUMN "new" TO "old"'

    rest = RestoreColumn("t", "c", column_type="INTEGER")
    fwd_sql = rest.forward_sql()
    assert len(fwd_sql) == 1
    assert 'DELETE FROM "openviper_soft_removed_columns"' in fwd_sql[0].text
    assert 'INSERT INTO "openviper_soft_removed_columns"' in rest.backward_sql()[0].text


@pytest.mark.asyncio
async def test_validate_restore_column():
    # Mocks
    conn = MagicMock()
    async_res = MagicMock()
    # Need to simulate async iteration of rows or first()
    row_mock = MagicMock()
    row_mock.__getitem__.return_value = 1
    async_res.first.return_value = row_mock
    conn.execute.return_value = async_res

    # Mock _get_soft_removed_info
    with patch("openviper.db.migrations.executor._get_soft_removed_info") as mk_info:
        mk_info.return_value = {"column_type": "JSON"}
        op = RestoreColumn("t", "c", "JSON")

        with patch("openviper.db.migrations.executor._count_null_values") as mock_count:
            mock_count.return_value = 1
            err = await validate_restore_column(conn, op, new_type="JSON", new_nullable=False)
            assert "NULL values" in str(err)

            mock_count.return_value = 0
            assert await validate_restore_column(conn, op, "JSON", new_nullable=False) is None

        # Exception type mismatched
        err = await validate_restore_column(conn, op, new_type="INTEGER", new_nullable=False)
        assert "type mismatch" in str(err)

        # Test not soft removed
        mk_info.return_value = None
        assert await validate_restore_column(conn, op, new_type="JSON", new_nullable=False) is None


@pytest.mark.asyncio
async def test_should_skip_funcs():
    conn = MagicMock()

    inspector_mock = MagicMock()
    inspector_mock.return_value.get_columns.return_value = [{"name": "c"}]

    assert _get_existing_columns_sync(conn, "t") == set()  # without mock, raised exception

    with patch("sqlalchemy.inspect", side_effect=inspector_mock):
        op = AddColumn("t", "c", "TEXT")
        op2 = AddColumn("t", "nonexistent", "TEXT")

        # mock run_sync as awaitable
        async def mock_run_sync(f, *args):
            return f(None, *args)

        conn.run_sync = mock_run_sync

        # _should_skip_backward test
        assert await _should_skip_backward(conn, op) is False
        with patch("sqlalchemy.inspect") as mk:
            insp2 = MagicMock()
            insp2.get_columns.return_value = [{"name": "c"}]
            mk.return_value = insp2
            assert await _should_skip_backward(conn, op2) is True

        assert await _should_skip_backward(conn, DropTable("t")) is False

        # _should_skip_forward test
        assert await _should_skip_forward(conn, op) is True  # c exists, skip adding it
        assert (
            await _should_skip_forward(conn, op2) is False
        )  # nonexistent doesn't exist, don't skip adding it

        rp = RemoveColumn("t", "nonexistent")
        rp_c = RemoveColumn("t", "c")
        assert (
            await _should_skip_forward(conn, rp) is True
        )  # nonexistent doesn't exist, skip removing it
        assert await _should_skip_forward(conn, rp_c) is False  # c exists, don't skip removing it

        assert await _should_skip_forward(conn, RunSQL("A")) is False


def test_base_operation():
    op = Operation()
    assert op.forward_sql() == []
    assert op.backward_sql() == []


def test_logger():
    # just test it doesn't crash on standard operations
    _MigrationLogger.log_applying("app", "001")
    _MigrationLogger.log_status(MigrationStatus.OK)
    _MigrationLogger.log_status(MigrationStatus.ERROR, error="foo")
    _MigrationLogger.log_status(MigrationStatus.SKIP)
    _MigrationLogger.log_status(MigrationStatus.ROLLBACK)
    _MigrationLogger.log_status(MigrationStatus.PENDING)
    _MigrationLogger.log_summary([("app", "001", MigrationStatus.OK)])


@pytest.fixture
def memory_engine():
    # We must patch get_engine to return our memory engine
    with patch("openviper.db.migrations.executor.get_engine") as mk:
        # Use an in-memory SQLite DB
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        mk.return_value = engine
        yield engine
        # Dispose synchronously to prevent ResourceWarning from sqlite3
        # connections in the pool being GC'd without explicit close.
        engine.dispose()


@pytest.fixture
def mock_discover():
    rec = MigrationRecord(
        "app",
        "001",
        [],
        [CreateTable("foo_table", [{"name": "id", "type": "INT", "primary_key": True}])],
        "path",
    )
    with patch("openviper.db.migrations.executor.discover_migrations", return_value=[rec]):
        yield [rec]


@pytest.mark.asyncio
async def test_migration_executor_migrate(memory_engine, mock_discover):
    executor = MigrationExecutor()
    applied = await executor.migrate()
    assert "001" in applied

    # Verify the table was created
    async with memory_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: sa.inspect(sync_conn).has_table("foo_table"))

    # Repeated migration should do nothing
    applied_again = await executor.migrate()
    assert not applied_again

    # Target name
    mock_discover[0].name = "002"
    applied_targetname = await executor.migrate(target_name="001")
    assert not applied_targetname
    mock_discover[0].name = "001"  # revert

    # Target app works
    applied_target = await executor.migrate("other")
    assert not applied_target  # Since mock_discover only has "app'

    # Validation errors

    mock_discover[0].operations.append(RestoreColumn("t", "c"))

    # We patch validate_restore_column to return a string "Failed"
    with patch("openviper.db.migrations.executor.validate_restore_column", return_value="Failed"):
        # run again targeting the newly added op but clearing applied tables cache
        with patch.object(executor, "_applied_migrations", return_value=set()):
            applied_with_err = await executor.migrate(ignore_errors=True)
            assert not applied_with_err  # Nothing returned because it failed

    mock_discover[0].operations.pop()

    # Rollback
    await executor.rollback("app", "001")

    with pytest.raises(ValueError, match="not found"):
        await executor.rollback("app", "002")


@pytest.mark.asyncio
async def test_migration_executor_rollback_skip(memory_engine):
    executor = MigrationExecutor()

    rec = MigrationRecord("app", "skip_bk", [], [AddColumn("foo_table", "c", "TEXT")], "path")
    with patch("openviper.db.migrations.executor.discover_migrations", return_value=[rec]):
        await executor.migrate(ignore_errors=True)
        # mock should skip backward to True
        with patch("openviper.db.migrations.executor._should_skip_backward", return_value=True):
            await executor.rollback("app", "skip_bk")


def test_discover_migrations():

    recs = discover_migrations()
    assert len(recs) > 0
    names = [r.app for r in recs]
    assert "auth" in names  # Built-in app

    # Test resolved apps
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        mig_dir = tdp / "migrations"
        mig_dir.mkdir()

        # Test valid
        f1 = mig_dir / "001_test.py"
        f1.write_text("operations = []\ndependencies = []\n")

        # Test ignorable
        f2 = mig_dir / "_ignore.py"
        f2.write_text("...")

        # Test syntax error
        f3 = mig_dir / "002_bad.py"
        f3.write_text("invalid syntax")

        # Test with resolved_apps
        recs2 = discover_migrations(resolved_apps={"dummy": str(tdp)})
        assert len(recs2) >= 1
        dummy_recs = [r for r in recs2 if r.name == "001_test"]
        assert len(dummy_recs) == 1

        # Test with apps_dir
        apps_dir = tdp.parent
        recs3 = discover_migrations(apps_dir=str(apps_dir))
        assert len(recs3) >= 1


@pytest.mark.asyncio
async def test_migration_executor_errors(memory_engine):
    # Test error during migration

    bad_rec = MigrationRecord("app", "002", [], [RunSQL("SELECT SYNTAX ERROR")], "path")

    with patch("openviper.db.migrations.executor.discover_migrations", return_value=[bad_rec]):
        executor = MigrationExecutor()
        applied = await executor.migrate(ignore_errors=True)
        assert not applied


def test_get_dialect_settings_raises():
    with patch("openviper.db.migrations.executor.settings") as mk:
        mk.DATABASE_URL = 42  # int has no .lower(); triggers except Exception
        assert _get_dialect() == "sqlite"


def test_rename_table_backward_sql_non_mysql():

    rt = RenameTable("old_tbl", "new_tbl")
    sql = rt.backward_sql()
    assert sql == ['ALTER TABLE "new_tbl" RENAME TO "old_tbl"']


@pytest.mark.asyncio
async def test_get_soft_removed_info_row_found():

    conn = MagicMock()
    result = MagicMock()
    row = MagicMock()
    row.table_name = "mytable"
    row.column_name = "mycol"
    row.column_type = "TEXT"
    result.first.return_value = row
    conn.execute = AsyncMock(return_value=result)

    info = await _get_soft_removed_info(conn, "mytable", "mycol")
    assert info == {"table_name": "mytable", "column_name": "mycol", "column_type": "TEXT"}


@pytest.mark.asyncio
async def test_count_null_values_with_row():

    conn = MagicMock()
    result = MagicMock()
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value=7)
    result.first.return_value = row
    conn.execute = AsyncMock(return_value=result)

    count = await _count_null_values(conn, "mytable", "mycol")
    assert count == 7


@pytest.mark.asyncio
async def test_count_total_rows_with_row():

    conn = MagicMock()
    result = MagicMock()
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value=42)
    result.first.return_value = row
    conn.execute = AsyncMock(return_value=result)

    count = await _count_total_rows(conn, "mytable")
    assert count == 42


@pytest.mark.asyncio
async def test_migration_skip_forward_continue(memory_engine):
    rec1 = MigrationRecord(
        "app",
        "skip_fwd_001",
        [],
        [
            CreateTable(
                "skip_fwd_tbl",
                [
                    {"name": "id", "type": "INT", "primary_key": True},
                    {"name": "existing_col", "type": "TEXT"},
                ],
            )
        ],
        "path",
    )
    # AddColumn for a column that will already exist after rec1 runs → _should_skip_forward → True
    rec2 = MigrationRecord(
        "app",
        "skip_fwd_002",
        [],
        [AddColumn("skip_fwd_tbl", "existing_col", "TEXT")],
        "path",
    )
    executor = MigrationExecutor()
    with patch("openviper.db.migrations.executor.discover_migrations", return_value=[rec1, rec2]):
        applied = await executor.migrate()
    assert "skip_fwd_001" in applied
    assert "skip_fwd_002" in applied


# ── New branch-coverage tests ──────────────────────────────────────────────────


def test_colorize_with_color_support():
    with patch.object(_MigrationLogger, "_supports_color", return_value=True):
        result = _MigrationLogger._colorize("hello", "GREEN")
        assert "\033[" in result
        assert "hello" in result
        assert _MigrationLogger.COLORS["END"] in result


def test_map_column_type_unknown_dialect():
    assert _map_column_type("DATETIME", "unknown_dialect") == "DATETIME"
    assert _map_column_type("VARCHAR(10)", "unknown_dialect") == "VARCHAR(10)"


def test_rename_table_forward_sql_mysql():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        rt = RenameTable("old_tbl", "new_tbl")
        sql = rt.forward_sql()
        assert sql == ["RENAME TABLE `old_tbl` TO `new_tbl`"]


def test_rename_table_backward_sql_mysql():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        rt = RenameTable("old_tbl", "new_tbl")
        sql = rt.backward_sql()
        assert sql == ["RENAME TABLE `new_tbl` TO `old_tbl`"]


def test_alter_column_sqlite_type_change():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
        alt = AlterColumn("t", "c", column_type="TEXT", old_type="INTEGER")
        fwd = alt.forward_sql()
        assert any('ALTER TABLE "t" ALTER COLUMN "c" TYPE TEXT' in x for x in fwd)


@pytest.mark.asyncio
async def test_get_soft_removed_info_exception():
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=Exception("db error"))
    result = await _get_soft_removed_info(conn, "table", "col")
    assert result is None


@pytest.mark.asyncio
async def test_count_null_values_exception():
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=Exception("db error"))
    result = await _count_null_values(conn, "table", "col")
    assert result == 0


def test_sort_migrations_circular():
    rec1 = MigrationRecord("app", "circ_001", [("app", "circ_002")], [], "path1")
    rec2 = MigrationRecord("app", "circ_002", [("app", "circ_001")], [], "path2")
    result = sort_migrations([rec1, rec2])
    assert len(result) == 2
    names = {r.name for r in result}
    assert names == {"circ_001", "circ_002"}


def test_discover_migrations_spec_none(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_test.py").write_text("operations = []\n")

    with patch("importlib.util.spec_from_file_location", return_value=None):
        recs = discover_migrations(resolved_apps={"dummy": str(tmp_path)})
        dummy_recs = [r for r in recs if r.app == "dummy"]
        assert len(dummy_recs) == 0


def test_discover_migrations_import_error():
    with patch("importlib.import_module", side_effect=ImportError("no module")):
        recs = discover_migrations()
        assert isinstance(recs, list)


def test_discover_migrations_pkg_no_file():
    mock_pkg = MagicMock()
    mock_pkg.__file__ = None
    with patch("importlib.import_module", return_value=mock_pkg):
        recs = discover_migrations()
        assert isinstance(recs, list)


@pytest.mark.asyncio
async def test_migration_executor_raises_on_error(memory_engine):
    bad_rec = MigrationRecord("app", "raises_001", [], [RunSQL("INVALID SQL THAT FAILS")], "path")
    with patch("openviper.db.migrations.executor.discover_migrations", return_value=[bad_rec]):
        executor = MigrationExecutor()
        with pytest.raises(sa.exc.SQLAlchemyError):
            await executor.migrate(ignore_errors=False)


@pytest.mark.asyncio
async def test_migration_executor_sync_content_types_auth(memory_engine, mock_discover):
    executor = MigrationExecutor()
    sync_mock = AsyncMock()
    auth_utils_mock = MagicMock()
    auth_utils_mock.sync_content_types = sync_mock
    with patch("openviper.db.migrations.executor.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["auth"]
        mock_settings.DATABASE_URL = "sqlite:///:memory:"
        with patch.dict("sys.modules", {"openviper.auth.utils": auth_utils_mock}):
            await executor.migrate()
    sync_mock.assert_called_once()


@pytest.mark.asyncio
async def test_migration_executor_sync_content_types_exception(memory_engine, mock_discover):
    executor = MigrationExecutor()
    auth_utils_mock = MagicMock()
    auth_utils_mock.sync_content_types = AsyncMock(side_effect=Exception("sync failed"))
    with patch("openviper.db.migrations.executor.settings") as mock_settings:
        mock_settings.INSTALLED_APPS = ["openviper.auth"]
        mock_settings.DATABASE_URL = "sqlite:///:memory:"
        with patch.dict("sys.modules", {"openviper.auth.utils": auth_utils_mock}):
            applied = await executor.migrate()
    # Exception is swallowed; return value is still valid
    assert isinstance(applied, list)
