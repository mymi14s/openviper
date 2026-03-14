"""Additional branch tests for openviper.db.migrations.executor."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.migrations.executor import (
    AddColumn,
    CreateTable,
    MigrationExecutor,
    MigrationRecord,
    Operation,
    RemoveColumn,
    RenameTable,
    RestoreColumn,
    RunSQL,
    _column_exists,
    _count_null_values,
    _discover_app_migrations,
    _get_existing_columns_sync,
    _get_soft_removed_info,
    _map_column_type,
    _quote_identifier,
    _should_skip_backward,
    _should_skip_forward,
    discover_migrations,
    validate_restore_column,
)


@asynccontextmanager
async def _begin_with(conn):
    yield conn


@pytest.mark.asyncio
async def test_migrate_target_app_and_target_name_filtering():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    records = [
        MigrationRecord(app="app1", name="0001_init", dependencies=[], operations=[], path=""),
        MigrationRecord(app="app1", name="0002_more", dependencies=[], operations=[], path=""),
        MigrationRecord(app="app2", name="0001_init", dependencies=[], operations=[], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table") as mock_table,
        patch("openviper.db.migrations.executor.sa") as mock_sa,
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="2026-03-13"))

        applied = await executor.migrate(target_app="app1", target_name="0001_init", verbose=False)

    assert applied == ["0001_init"]
    assert conn.execute.called
    assert mock_table.called
    assert mock_sa.insert.called


@pytest.mark.asyncio
async def test_migrate_restore_validation_error_with_ignore_errors_continues():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    records = [
        MigrationRecord(
            app="app",
            name="0001_restore",
            dependencies=[],
            operations=[RestoreColumn(table_name="items", column_name="deleted_col")],
            path="",
        ),
        MigrationRecord(
            app="app",
            name="0002_ok",
            dependencies=[],
            operations=[RunSQL("SELECT 1")],
            path="",
        ),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch(
            "openviper.db.migrations.executor._should_skip_forward",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "openviper.db.migrations.executor.validate_restore_column",
            new_callable=AsyncMock,
            return_value="blocked",
        ),
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []

        applied = await executor.migrate(verbose=False, ignore_errors=True)

    assert applied == ["0002_ok"]


def test_map_column_type_unknown_dialect_returns_unchanged():
    result = _map_column_type("BOOLEAN", "unknown_dialect")
    assert result == "BOOLEAN"


def test_map_column_type_no_regex_match_returns_unchanged():
    result = _map_column_type("123-INVALID!", "postgresql")
    assert result == "123-INVALID!"


def test_map_column_type_datetime_postgresql_use_tz():
    with patch("openviper.db.migrations.executor.settings") as s:
        s.USE_TZ = True
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            result = _map_column_type("DATETIME", "postgresql")
    assert result == "TIMESTAMP WITH TIME ZONE"


def test_map_column_type_datetime_postgresql_no_tz():
    with patch("openviper.db.migrations.executor.settings") as s:
        s.USE_TZ = False
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            result = _map_column_type("DATETIME", "postgresql")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_should_skip_forward_create_table_auth_users_custom_model():
    conn = AsyncMock()
    op = CreateTable(table_name="auth_users", columns=[])
    with patch("openviper.db.migrations.executor.settings") as s:
        s.USER_MODEL = "myapp.models.CustomUser"
        result = await _should_skip_forward(conn, op)
    assert result is True


@pytest.mark.asyncio
async def test_should_skip_forward_create_table_auth_users_default_model():
    conn = AsyncMock()
    op = CreateTable(table_name="auth_users", columns=[])
    with patch("openviper.db.migrations.executor.settings") as s:
        s.USER_MODEL = "openviper.auth.models.User"
        result = await _should_skip_forward(conn, op)
    assert result is False


@pytest.mark.asyncio
async def test_should_skip_forward_add_column_already_exists():
    conn = AsyncMock()
    op = AddColumn(table_name="t", column_name="col", column_type="TEXT")
    with patch(
        "openviper.db.migrations.executor._column_exists", new_callable=AsyncMock, return_value=True
    ):
        result = await _should_skip_forward(conn, op)
    assert result is True


@pytest.mark.asyncio
async def test_should_skip_forward_add_column_not_exists():
    conn = AsyncMock()
    op = AddColumn(table_name="t", column_name="col", column_type="TEXT")
    with patch(
        "openviper.db.migrations.executor._column_exists",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await _should_skip_forward(conn, op)
    assert result is False


@pytest.mark.asyncio
async def test_should_skip_forward_remove_column_not_exists():
    conn = AsyncMock()
    op = RemoveColumn(table_name="t", column_name="col")
    with patch(
        "openviper.db.migrations.executor._column_exists",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await _should_skip_forward(conn, op)
    assert result is True


@pytest.mark.asyncio
async def test_should_skip_forward_remove_column_exists():
    conn = AsyncMock()
    op = RemoveColumn(table_name="t", column_name="col")
    with patch(
        "openviper.db.migrations.executor._column_exists", new_callable=AsyncMock, return_value=True
    ):
        result = await _should_skip_forward(conn, op)
    assert result is False


@pytest.mark.asyncio
async def test_should_skip_backward_returns_false_for_run_sql():
    conn = AsyncMock()
    op = RunSQL("SELECT 1")
    result = await _should_skip_backward(conn, op)
    assert result is False


def test_quote_identifier_mysql():
    assert _quote_identifier("my_table", "mysql") == "`my_table`"


def test_quote_identifier_mssql():
    assert _quote_identifier("my_table", "mssql") == "[my_table]"


def test_quote_identifier_default():
    assert _quote_identifier("my_table", "postgresql") == '"my_table"'


def test_rename_table_mysql_forward():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        op = RenameTable(old_name="old", new_name="new")
        sql = op.forward_sql()
    assert "RENAME TABLE" in sql[0]
    assert "`old`" in sql[0]


def test_rename_table_mssql_forward():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
        op = RenameTable(old_name="old", new_name="new")
        sql = op.forward_sql()
    assert "sp_rename" in sql[0]


def test_rename_table_mysql_backward():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
        op = RenameTable(old_name="old", new_name="new")
        sql = op.backward_sql()
    assert "RENAME TABLE" in sql[0]
    assert "`new`" in sql[0]


def test_rename_table_mssql_backward():
    with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
        op = RenameTable(old_name="old", new_name="new")
        sql = op.backward_sql()
    assert "sp_rename" in sql[0]


@pytest.mark.asyncio
async def test_migrate_verbose_true_prints_output():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    records = [
        MigrationRecord(app="app1", name="0001_init", dependencies=[], operations=[], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
        patch("builtins.print") as mock_print,
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate(verbose=True)

    assert mock_print.called
    assert "0001_init" in applied


@pytest.mark.asyncio
async def test_migrate_sync_content_types_exception_logged():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    records = [
        MigrationRecord(app="auth", name="0001_init", dependencies=[], operations=[], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
        patch(
            "openviper.auth.utils.sync_content_types",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ),
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = ["openviper.auth"]
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate(verbose=False)

    assert applied == ["0001_init"]


@pytest.mark.asyncio
async def test_rollback_executes_backward_sql():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    op = RunSQL(sql="CREATE TABLE x(id INT)", reverse_sql="DROP TABLE x")
    records = [
        MigrationRecord(app="app", name="0001_init", dependencies=[], operations=[op], path=""),
    ]

    with (
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch(
            "openviper.db.migrations.executor._should_skip_backward",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        await executor.rollback("app", "0001_init")

    assert conn.execute.called


@pytest.mark.asyncio
async def test_rollback_raises_when_migration_not_found():
    executor = MigrationExecutor()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(AsyncMock())

    with (
        patch("openviper.db.migrations.executor.discover_migrations", return_value=[]),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
    ):
        with pytest.raises(ValueError, match="not found"):
            await executor.rollback("app", "0001_init")


# ── Operation base class ──────────────────────────────────────────────────────


def test_operation_base_methods_return_empty_list():

    op = Operation()
    assert op.forward_sql() == []
    assert op.backward_sql() == []


# ── CreateTable.backward_sql ──────────────────────────────────────────────────


def test_create_table_backward_sql_produces_drop_statement():
    ct = CreateTable(table_name="things", columns=[])
    with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
        sql = ct.backward_sql()
    assert len(sql) == 1
    assert "DROP TABLE IF EXISTS" in sql[0]
    assert "things" in sql[0]


# ── _discover_app_migrations branches ────────────────────────────────────────


def test_discover_app_migrations_no_migrations_dir_returns_empty(tmp_path):

    records = []
    _discover_app_migrations(tmp_path, records)
    assert records == []


def test_discover_app_migrations_skips_underscore_files(tmp_path):

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "_helpers.py").write_text("# private")
    records = []
    _discover_app_migrations(tmp_path, records)
    assert records == []


def test_discover_app_migrations_spec_none_skips_file(tmp_path):

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_init.py").write_text("operations = []")
    records = []
    with patch("importlib.util.spec_from_file_location", return_value=None):
        _discover_app_migrations(tmp_path, records)
    assert records == []


def test_discover_app_migrations_exec_module_error_skips(tmp_path):

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_init.py").write_text("operations = []")
    records = []
    mock_loader = MagicMock()
    mock_loader.exec_module.side_effect = RuntimeError("bad module")
    mock_spec = MagicMock()
    mock_spec.loader = mock_loader
    with patch("importlib.util.spec_from_file_location", return_value=mock_spec):
        _discover_app_migrations(tmp_path, records)
    assert records == []


# ── discover_migrations builtin/legacy branches ───────────────────────────────


def test_discover_migrations_builtin_import_error_skips():

    with patch(
        "openviper.db.migrations.executor.importlib.import_module",
        side_effect=ImportError("not found"),
    ):
        records = discover_migrations(resolved_apps={}, apps_dir=None)
    assert records == []


def test_discover_migrations_pkg_file_none_skips():

    mock_pkg = MagicMock()
    mock_pkg.__file__ = None
    with patch("openviper.db.migrations.executor.importlib.import_module", return_value=mock_pkg):
        records = discover_migrations(resolved_apps={}, apps_dir=None)
    assert records == []


def test_discover_migrations_legacy_apps_dir_skips_non_dirs(tmp_path):

    (tmp_path / "notadir.txt").write_text("data")
    myapp = tmp_path / "myapp"
    myapp.mkdir()
    # myapp has no migrations/ subdir, so no records discovered
    with patch(
        "openviper.db.migrations.executor.importlib.import_module",
        side_effect=ImportError("no builtins"),
    ):
        records = discover_migrations(resolved_apps=None, apps_dir=str(tmp_path))
    assert records == []


# ── _get_existing_columns_sync and _column_exists ────────────────────────────


def test_get_existing_columns_sync_returns_column_name_set():

    mock_conn = MagicMock()
    mock_insp = MagicMock()
    mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "email"}]
    with patch("openviper.db.migrations.executor.sa") as mock_sa:
        mock_sa.inspect.return_value = mock_insp
        result = _get_existing_columns_sync(mock_conn, "users")
    assert result == {"id", "email"}


@pytest.mark.asyncio
async def test_column_exists_when_present():

    mock_conn = AsyncMock()
    mock_conn.run_sync.return_value = {"id", "email", "name"}
    result = await _column_exists(mock_conn, "users", "email")
    assert result is True


@pytest.mark.asyncio
async def test_column_exists_when_absent():

    mock_conn = AsyncMock()
    mock_conn.run_sync.return_value = {"id", "name"}
    result = await _column_exists(mock_conn, "users", "missing_col")
    assert result is False


# ── _get_soft_removed_info: row-found path ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_soft_removed_info_returns_dict_when_row_found():

    mock_row = MagicMock()
    mock_row.table_name = "users"
    mock_row.column_name = "deleted_at"
    mock_row.column_type = "DATETIME"
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_result

    with (
        patch("openviper.db.migrations.executor._get_soft_removed_table"),
        patch("openviper.db.migrations.executor.sa"),
    ):
        result = await _get_soft_removed_info(mock_conn, "users", "deleted_at")

    assert result is not None
    assert result["table_name"] == "users"
    assert result["column_name"] == "deleted_at"
    assert result["column_type"] == "DATETIME"


# ── _count_null_values: row-found path ───────────────────────────────────────


@pytest.mark.asyncio
async def test_count_null_values_returns_row_count_when_row_found():

    mock_result = MagicMock()
    mock_result.first.return_value = [7]
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_result

    with (
        patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"),
        patch(
            "openviper.db.migrations.executor._quote_identifier", side_effect=lambda n, _: f'"{n}"'
        ),
        patch("openviper.db.migrations.executor.sa") as mock_sa,
    ):
        mock_sa.text.return_value = MagicMock()
        result = await _count_null_values(mock_conn, "items", "col")

    assert result == 7


# ── validate_restore_column: return None path ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_restore_column_returns_none_when_types_compatible_and_nullable():

    op = RestoreColumn(table_name="t", column_name="c", column_type="TEXT")
    mock_conn = AsyncMock()
    soft_info = {"column_type": "TEXT", "table_name": "t", "column_name": "c"}

    with patch(
        "openviper.db.migrations.executor._get_soft_removed_info",
        new_callable=AsyncMock,
        return_value=soft_info,
    ):
        result = await validate_restore_column(mock_conn, op, new_type="TEXT", new_nullable=True)

    assert result is None


# ── migrate: target_app skips non-matching app ────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_target_app_skips_non_matching_app_record():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    # app2 comes BEFORE app1 so the continue fires before any break
    records = [
        MigrationRecord(app="app2", name="0001_init", dependencies=[], operations=[], path=""),
        MigrationRecord(app="app1", name="0001_init", dependencies=[], operations=[], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate(target_app="app1")

    assert applied == ["0001_init"]


# ── migrate: _should_skip_forward returns True → continue ────────────────────


@pytest.mark.asyncio
async def test_migrate_continues_when_should_skip_forward_returns_true():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    op = AddColumn(table_name="t", column_name="c", column_type="TEXT")
    records = [
        MigrationRecord(app="app", name="0001_add", dependencies=[], operations=[op], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
        patch(
            "openviper.db.migrations.executor._should_skip_forward",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate()

    # Migration IS still applied (tracked), just the op SQL was skipped
    assert "0001_add" in applied


# ── migrate: verbose=True error path ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_verbose_error_logs_status_and_continues():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)
    conn.execute.side_effect = RuntimeError("DB boom")

    records = [
        MigrationRecord(
            app="app", name="0001_err", dependencies=[], operations=[RunSQL("SELECT 1")], path=""
        ),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
        patch(
            "openviper.db.migrations.executor._should_skip_forward",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("builtins.print") as mock_print,
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate(verbose=True, ignore_errors=True)

    assert mock_print.called
    assert applied == []


# ── migrate: invalidate cache after applying ──────────────────────────────────


@pytest.mark.asyncio
async def test_migrate_invalidates_soft_removed_cache_after_applying():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    records = [
        MigrationRecord(app="app", name="0001_init", dependencies=[], operations=[], path=""),
    ]

    with (
        patch.object(executor, "_ensure_migration_table", new_callable=AsyncMock),
        patch.object(executor, "_applied_migrations", new_callable=AsyncMock, return_value=set()),
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch("openviper.db.migrations.executor.settings") as mock_settings,
        patch("openviper.db.migrations.executor.timezone") as mock_timezone,
        patch("openviper.db.executor.invalidate_soft_removed_cache") as mock_invalidate,
    ):
        mock_settings.USE_TZ = False
        mock_settings.INSTALLED_APPS = []
        mock_timezone.now.return_value = MagicMock(replace=MagicMock(return_value="now"))

        applied = await executor.migrate()

    assert "0001_init" in applied
    mock_invalidate.assert_called_once()


# ── rollback: _should_skip_backward returns True → continue ──────────────────


@pytest.mark.asyncio
async def test_rollback_skips_op_when_should_skip_backward_returns_true():
    executor = MigrationExecutor()
    conn = AsyncMock()
    engine = MagicMock()
    engine.begin = lambda: _begin_with(conn)

    op = AddColumn(table_name="t", column_name="c", column_type="TEXT")
    records = [
        MigrationRecord(app="app", name="0001_add", dependencies=[], operations=[op], path=""),
    ]

    with (
        patch("openviper.db.migrations.executor.discover_migrations", return_value=records),
        patch(
            "openviper.db.migrations.executor.get_engine",
            new_callable=AsyncMock,
            return_value=engine,
        ),
        patch("openviper.db.migrations.executor._get_migration_table"),
        patch("openviper.db.migrations.executor.sa"),
        patch(
            "openviper.db.migrations.executor._should_skip_backward",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await executor.rollback("app", "0001_add")

    # Only the migration-table DELETE should have been called, not the op's SQL
    # conn.execute called for sa.delete(table).where(...) only
    assert conn.execute.called
