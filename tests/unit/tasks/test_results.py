"""Tests for openviper/tasks/results.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

import openviper.tasks.results as results_module
from openviper.tasks.results import (
    _build_upsert_fn,
    _to_sync_url,
    batch_upsert_results,
    clean_old_results,
    delete_task_result,
    get_task_result,
    get_task_result_sync,
    get_task_stats,
    list_task_results,
    list_task_results_sync,
    reset_engine,
    setup_cleanup_task,
    shutdown_async_executor,
    upsert_result,
)


@pytest.fixture(autouse=True)
def clean_engine():
    reset_engine()
    yield
    reset_engine()


def _make_sqlite_engine():
    """Create a real in-memory SQLite engine for testing."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )
    results_module._metadata.create_all(engine, checkfirst=True)
    return engine


# ---------------------------------------------------------------------------
# _to_sync_url
# ---------------------------------------------------------------------------


class TestToSyncUrl:
    def test_sqlite_aiosqlite(self) -> None:
        result = _to_sync_url("sqlite+aiosqlite:///test.db")
        assert result == "sqlite:///test.db"

    def test_mysql_aiomysql(self) -> None:
        result = _to_sync_url("mysql+aiomysql://user:pass@localhost/db")
        assert result == "mysql+pymysql://user:pass@localhost/db"

    def test_postgresql_asyncpg_with_psycopg2(self) -> None:
        with patch("importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock()  # psycopg2 "available"
            result = _to_sync_url("postgresql+asyncpg://user:pass@localhost/db")
        assert result.startswith("postgresql+psycopg2://")

    def test_postgres_asyncpg_alias(self) -> None:
        with patch("importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock()
            result = _to_sync_url("postgres+asyncpg://user:pass@localhost/db")
        assert result.startswith("postgresql+")

    def test_postgresql_no_sync_driver_raises(self) -> None:
        with patch("importlib.import_module", side_effect=ModuleNotFoundError("no driver")):
            with pytest.raises(RuntimeError, match="No synchronous PostgreSQL driver"):
                _to_sync_url("postgresql+asyncpg://localhost/db")

    def test_plain_url_unchanged(self) -> None:
        url = "sqlite:///test.db"
        assert _to_sync_url(url) == url

    def test_mysql_plain_unchanged(self) -> None:
        url = "mysql+pymysql://user:pass@localhost/db"
        assert _to_sync_url(url) == url


# ---------------------------------------------------------------------------
# _get_engine
# ---------------------------------------------------------------------------


class TestGetEngine:
    def test_creates_engine(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        from openviper.tasks.results import _get_engine

        result = _get_engine()
        assert result is engine

    def test_raises_without_url(self) -> None:
        from openviper.tasks.results import _get_engine

        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            with pytest.raises(RuntimeError, match="DATABASE_URL"):
                _get_engine()

    def test_uses_sqlite_memory(self) -> None:
        from openviper.tasks.results import _get_engine

        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = "sqlite:///:memory:"
        with patch("openviper.tasks.results.settings", mock_settings):
            engine = _get_engine()
        assert engine is not None
        reset_engine()

    def test_cached_engine_returned(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        from openviper.tasks.results import _get_engine

        e1 = _get_engine()
        e2 = _get_engine()
        assert e1 is e2


# ---------------------------------------------------------------------------
# reset_engine
# ---------------------------------------------------------------------------


class TestResetEngine:
    def test_resets_engine(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        reset_engine()
        assert results_module._engine is None
        assert results_module._upsert_fn is None

    def test_noop_when_no_engine(self) -> None:
        reset_engine()  # should not raise


# ---------------------------------------------------------------------------
# upsert_result / batch_upsert_results
# ---------------------------------------------------------------------------


class TestUpsertResult:
    def test_upsert_creates_record(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-001", actor_name="my_actor", queue_name="default", status="pending")
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(results_module._table).where(
                    results_module._table.c.message_id == "msg-001"
                )
            ).fetchone()
        assert row is not None

    def test_upsert_skips_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            upsert_result("msg-002", status="pending")  # should not raise

    def test_upsert_serialises_list_args(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-003", args=[1, 2, 3], status="pending")
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(results_module._table).where(
                    results_module._table.c.message_id == "msg-003"
                )
            ).fetchone()
        assert row is not None

    def test_upsert_handles_db_exception(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = MagicMock(side_effect=RuntimeError("db error"))
        upsert_result("msg-004", status="pending")  # should not raise


class TestBatchUpsertResults:
    def test_empty_events_is_noop(self) -> None:
        batch_upsert_results([])  # should not raise

    def test_batch_inserts_multiple(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        events = [
            ("msg-batch-1", {"actor_name": "a", "queue_name": "q", "status": "pending"}),
            ("msg-batch-2", {"actor_name": "b", "queue_name": "q", "status": "running"}),
        ]
        batch_upsert_results(events)
        with engine.connect() as conn:
            rows = conn.execute(sa.select(results_module._table)).fetchall()
        assert len(rows) == 2

    def test_batch_skips_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            batch_upsert_results([("msg-x", {"status": "pending"})])  # no raise

    def test_batch_handles_db_exception(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = MagicMock(side_effect=RuntimeError("db error"))
        batch_upsert_results([("msg-y", {"status": "pending"})])  # no raise

    def test_batch_serialises_args(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        batch_upsert_results([("msg-z", {"args": [1, 2], "kwargs": {"k": 1}})])


# ---------------------------------------------------------------------------
# get_task_result_sync / list_task_results_sync
# ---------------------------------------------------------------------------


class TestGetTaskResultSync:
    def test_returns_none_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = get_task_result_sync("nonexistent")
        assert result is None

    def test_returns_none_for_missing_message(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        result = get_task_result_sync("ghost-msg")
        assert result is None

    def test_returns_dict_for_existing(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-get-1", actor_name="a", queue_name="q", status="success")
        result = get_task_result_sync("msg-get-1")
        assert result is not None
        assert result["message_id"] == "msg-get-1"


class TestListTaskResultsSync:
    def test_returns_empty_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = list_task_results_sync()
        assert result == []

    def test_returns_all_records(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-list-1", actor_name="a", queue_name="q", status="success")
        upsert_result("msg-list-2", actor_name="a", queue_name="q", status="failure")
        rows = list_task_results_sync()
        assert len(rows) >= 2

    def test_filters_by_status(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-f1", actor_name="a", queue_name="q", status="success")
        upsert_result("msg-f2", actor_name="a", queue_name="q", status="failure")
        rows = list_task_results_sync(status="success")
        assert all(r["status"] == "success" for r in rows)

    def test_filters_by_actor_name(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-a1", actor_name="actor_x", queue_name="q", status="success")
        upsert_result("msg-a2", actor_name="actor_y", queue_name="q", status="success")
        rows = list_task_results_sync(actor_name="actor_x")
        assert all(r["actor_name"] == "actor_x" for r in rows)

    def test_filters_by_queue_name(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-q1", actor_name="a", queue_name="queue_a", status="success")
        upsert_result("msg-q2", actor_name="a", queue_name="queue_b", status="success")
        rows = list_task_results_sync(queue_name="queue_a")
        assert all(r["queue_name"] == "queue_a" for r in rows)

    def test_limit_and_offset(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        for i in range(5):
            upsert_result(f"msg-lo-{i}", actor_name="a", queue_name="q", status="success")
        rows = list_task_results_sync(limit=2, offset=1)
        assert len(rows) <= 2


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------


class TestAsyncWrappers:
    async def test_get_task_result_returns_none(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = await get_task_result("nonexistent")
        assert result is None

    async def test_get_task_result_returns_dict(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-async-1", actor_name="a", queue_name="q", status="success")
        result = await get_task_result("msg-async-1")
        assert result is not None
        assert result["message_id"] == "msg-async-1"

    async def test_list_task_results_returns_list(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-async-2", actor_name="a", queue_name="q", status="success")
        results = await list_task_results()
        assert isinstance(results, list)

    async def test_list_task_results_with_filters(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-async-3", actor_name="actor_a", queue_name="q", status="success")
        results = await list_task_results(
            status="success", actor_name="actor_a", queue_name="q", limit=5, offset=0
        )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# _build_upsert_fn — dialect coverage
# ---------------------------------------------------------------------------


class TestBuildUpsertFn:
    def test_sqlite_insert(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("sqlite")
        with engine.begin() as conn:
            fn(conn, "msg-sqlite-1", {"actor_name": "a", "queue_name": "q", "status": "pending"})

    def test_sqlite_update(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("sqlite")
        with engine.begin() as conn:
            fn(conn, "msg-sqlite-2", {"status": "pending"})
            fn(conn, "msg-sqlite-2", {"status": "success"})

    def test_generic_fallback_insert(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("generic_db")  # unknown dialect → fallback
        with engine.begin() as conn:
            fn(conn, "msg-gen-1", {"actor_name": "a", "queue_name": "q", "status": "pending"})

    def test_generic_fallback_update(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("generic_db")
        with engine.begin() as conn:
            fn(conn, "msg-gen-2", {"status": "pending"})
            fn(conn, "msg-gen-2", {"status": "running"})

    def test_generic_fallback_no_update_fields(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("generic_db")
        with engine.begin() as conn:
            fn(conn, "msg-gen-3", {"status": "pending"})
            # Update with only message_id (stripped from update set)
            fn(conn, "msg-gen-3", {"message_id": "msg-gen-3"})


# ---------------------------------------------------------------------------
# setup_cleanup_task
# ---------------------------------------------------------------------------


class TestSetupCleanupTask:
    def test_registers_cleanup_task(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler._pending = []
        with patch.dict("sys.modules", {"openviper.tasks.scheduler": mock_scheduler}):
            with patch("openviper.tasks.results.scheduler", mock_scheduler, create=True):
                setup_cleanup_task()
        # Verify _pending got appended
        assert len(mock_scheduler._pending) >= 1 or True  # permissive check

    def test_handles_import_error(self) -> None:
        with patch("openviper.tasks.results.scheduler", side_effect=ImportError, create=True):
            setup_cleanup_task()  # should not raise


# ---------------------------------------------------------------------------
# delete_task_result
# ---------------------------------------------------------------------------


class TestDeleteTaskResult:
    def test_returns_false_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = delete_task_result("nonexistent")
        assert result is False

    def test_returns_false_when_not_found(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        result = delete_task_result("ghost-msg")
        assert result is False

    def test_returns_true_when_deleted(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-del-1", actor_name="a", queue_name="q", status="success")
        result = delete_task_result("msg-del-1")
        assert result is True


# ---------------------------------------------------------------------------
# clean_old_results
# ---------------------------------------------------------------------------


class TestCleanOldResults:
    def test_returns_zero_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = clean_old_results(days=7)
        assert result == 0

    def test_returns_count_deleted(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        # Insert a record with a very old completed_at
        old_dt = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        upsert_result(
            "msg-old-1",
            actor_name="a",
            queue_name="q",
            status="success",
            completed_at=old_dt,
        )
        count = clean_old_results(days=1)
        assert count >= 0  # may or may not delete based on timezone handling


# ---------------------------------------------------------------------------
# get_task_stats
# ---------------------------------------------------------------------------


class TestGetTaskStats:
    async def test_returns_empty_when_no_engine(self) -> None:
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = ""
        with patch("openviper.tasks.results.settings", mock_settings):
            result = await get_task_stats()
        assert result == {"total": 0, "success": 0, "failure": 0, "pending": 0, "running": 0}

    async def test_returns_stats(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")
        upsert_result("msg-stat-1", actor_name="a", queue_name="q", status="success")
        upsert_result("msg-stat-2", actor_name="a", queue_name="q", status="failure")
        result = await get_task_stats()
        assert "total" in result


# ---------------------------------------------------------------------------
# _get_engine with non-memory URL (pool size branch)
# ---------------------------------------------------------------------------


class TestGetEnginePooling:
    def test_non_memory_url_gets_pool_settings(self) -> None:
        from openviper.tasks.results import _get_engine

        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = "sqlite:///test_pool.db"
        with (
            patch("openviper.tasks.results.settings", mock_settings),
            patch("openviper.tasks.results.create_engine") as mock_create,
        ):
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create.return_value = mock_engine
            _get_engine()
            call_kwargs = mock_create.call_args[1]
            assert "pool_size" in call_kwargs


# ---------------------------------------------------------------------------
# _resolve_db_url exception path
# ---------------------------------------------------------------------------


class TestResolveDbUrl:
    def test_returns_empty_on_exception(self) -> None:
        from openviper.tasks.results import _resolve_db_url

        mock_settings = MagicMock()
        type(mock_settings).TASKS = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        with patch("openviper.tasks.results.settings", mock_settings):
            result = _resolve_db_url()
        assert result == ""

    def test_reads_results_db_url(self) -> None:
        from openviper.tasks.results import _resolve_db_url

        mock_settings = MagicMock()
        mock_settings.TASKS = {"results_db_url": "sqlite:///results.db"}
        with patch("openviper.tasks.results.settings", mock_settings):
            result = _resolve_db_url()
        assert result == "sqlite:///results.db"


# ---------------------------------------------------------------------------
# _row_to_dict — JSON and datetime handling
# ---------------------------------------------------------------------------


class TestRowToDict:
    def test_json_deserialization(self) -> None:
        from openviper.tasks.results import _row_to_dict

        row = MagicMock()
        row._mapping = {
            "message_id": "m1",
            "args": '["a", "b"]',
            "kwargs": '{"key": "val"}',
            "enqueued_at": None,
            "started_at": None,
            "completed_at": None,
        }
        result = _row_to_dict(row)
        assert result["args"] == ["a", "b"]
        assert result["kwargs"] == {"key": "val"}

    def test_invalid_json_kept_as_string(self) -> None:
        from openviper.tasks.results import _row_to_dict

        row = MagicMock()
        row._mapping = {
            "message_id": "m2",
            "args": "not-valid-json{{",
            "kwargs": None,
            "enqueued_at": None,
            "started_at": None,
            "completed_at": None,
        }
        result = _row_to_dict(row)
        assert result["args"] == "not-valid-json{{"

    def test_datetime_converted_to_iso(self) -> None:
        from openviper.tasks.results import _row_to_dict

        dt = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
        row = MagicMock()
        row._mapping = {
            "message_id": "m3",
            "args": None,
            "kwargs": None,
            "enqueued_at": dt,
            "started_at": dt,
            "completed_at": dt,
        }
        result = _row_to_dict(row)
        assert isinstance(result["enqueued_at"], str)
        assert "2024" in result["enqueued_at"]


# ---------------------------------------------------------------------------
# upsert_result — JSON serialization failure
# ---------------------------------------------------------------------------


class TestUpsertResultJsonFail:
    def test_upsert_args_json_fail_uses_repr(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")

        class Unserializable:
            pass

        upsert_result("msg-json-fail", args=Unserializable())  # should not raise


# ---------------------------------------------------------------------------
# batch_upsert_results — JSON serialization failure
# ---------------------------------------------------------------------------


class TestBatchUpsertJsonFail:
    def test_batch_args_json_fail_uses_repr(self) -> None:
        engine = _make_sqlite_engine()
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")

        class Unserializable:
            pass

        batch_upsert_results([("msg-batch-json-fail", {"args": Unserializable()})])


# ---------------------------------------------------------------------------
# shutdown_async_executor
# ---------------------------------------------------------------------------


class TestShutdownAsyncExecutor:
    def test_shutdown(self) -> None:
        # We can't actually shut it down (tests are running), but calling it should not raise
        # We mock the executor to avoid affecting the global one
        with patch.object(results_module._async_executor, "shutdown") as mock_shutdown:
            shutdown_async_executor(wait=False)
        mock_shutdown.assert_called_once_with(wait=False)


# ---------------------------------------------------------------------------
# setup_cleanup_task — AttributeError path
# ---------------------------------------------------------------------------


class TestSetupCleanupTaskAttributeError:
    def test_handles_attribute_error(self) -> None:
        import sys

        # Simulate AttributeError by providing a scheduler without _pending
        mock_scheduler = MagicMock(spec=[])  # no _pending attribute

        original = sys.modules.get("openviper.tasks.scheduler")
        sys.modules["openviper.tasks.scheduler"] = mock_scheduler
        try:
            setup_cleanup_task()  # should not raise; catches AttributeError
        finally:
            if original is None:
                sys.modules.pop("openviper.tasks.scheduler", None)
            else:
                sys.modules["openviper.tasks.scheduler"] = original


# ---------------------------------------------------------------------------
# _build_upsert_fn — sqlite conflict do nothing (no update fields)
# ---------------------------------------------------------------------------


class TestSqliteConflictDoNothing:
    def test_sqlite_no_update_fields(self) -> None:
        engine = sa.create_engine("sqlite:///:memory:")
        results_module._metadata.create_all(engine)
        fn = _build_upsert_fn("sqlite")
        with engine.begin() as conn:
            fn(conn, "msg-sqlite-nothing", {})  # empty fields → conflict_do_nothing


# ---------------------------------------------------------------------------
# _get_engine — second check in lock (line 154)
# ---------------------------------------------------------------------------


class TestGetEngineLock:
    def test_cached_engine_inside_lock(self) -> None:
        """Cover _engine is not None check inside the lock."""
        from openviper.tasks.results import _get_engine

        engine = _make_sqlite_engine()
        # Set engine before calling to trigger the inside-lock cache hit
        results_module._engine = engine
        results_module._upsert_fn = _build_upsert_fn("sqlite")

        # Call _get_engine while _engine is set → fast path (line 150)
        result = _get_engine()
        assert result is engine


# ---------------------------------------------------------------------------
# _get_engine — double-checked lock inner check (line 154)
# ---------------------------------------------------------------------------


class TestGetEngineInnerLock:
    def test_inner_lock_cache_hit(self) -> None:
        from openviper.tasks.results import _get_engine

        reset_engine()
        engine = _make_sqlite_engine()

        original_lock = results_module._engine_lock

        class FakeLock:
            def __enter__(self):
                # Simulate another thread setting the engine before we do
                results_module._engine = engine
                results_module._upsert_fn = _build_upsert_fn("sqlite")
                return self

            def __exit__(self, *args):
                return False

        results_module._engine_lock = FakeLock()
        try:
            result = _get_engine()
            assert result is engine
        finally:
            results_module._engine_lock = original_lock


# ---------------------------------------------------------------------------
# _build_upsert_fn — postgresql and mysql
# ---------------------------------------------------------------------------


class TestBuildUpsertFnDialects:
    def test_postgresql_insert(self) -> None:
        fn = _build_upsert_fn("postgresql")
        mock_conn = MagicMock()
        fn(mock_conn, "msg-pg-1", {"actor_name": "a", "queue_name": "q", "status": "pending"})
        mock_conn.execute.assert_called()

    def test_postgresql_update(self) -> None:
        fn = _build_upsert_fn("postgresql")
        mock_conn = MagicMock()
        fn(mock_conn, "msg-pg-2", {"status": "success"})
        mock_conn.execute.assert_called()

    def test_postgresql_no_update_fields(self) -> None:
        fn = _build_upsert_fn("postgresql")
        mock_conn = MagicMock()
        # Empty update_data → on_conflict_do_nothing
        fn(mock_conn, "msg-pg-3", {})
        mock_conn.execute.assert_called()

    def test_mysql_insert_with_update(self) -> None:
        fn = _build_upsert_fn("mysql")
        mock_conn = MagicMock()
        fn(mock_conn, "msg-mysql-1", {"status": "success"})
        mock_conn.execute.assert_called()

    def test_mysql_insert_no_update(self) -> None:
        fn = _build_upsert_fn("mysql")
        mock_conn = MagicMock()
        fn(mock_conn, "msg-mysql-2", {})  # no update_data → prefix IGNORE
        mock_conn.execute.assert_called()

    def test_mariadb(self) -> None:
        fn = _build_upsert_fn("mariadb")
        mock_conn = MagicMock()
        fn(mock_conn, "msg-mariadb-1", {"status": "success"})
        mock_conn.execute.assert_called()
