"""Tests for openviper/tasks/results.py."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.results as results_module
from openviper.tasks.results import (
    _build_upsert_fn,
    _resolve_db_url,
    _row_to_dict,
    _to_sync_url,
    batch_upsert_results,
    get_task_result,
    get_task_result_sync,
    list_task_results,
    list_task_results_sync,
    reset_engine,
    upsert_result,
)

_SQLITE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def clean_engine():
    """Dispose engine before and after each test."""
    reset_engine()
    yield
    reset_engine()


# ---------------------------------------------------------------------------
# _to_sync_url
# ---------------------------------------------------------------------------


class TestToSyncUrl:
    def test_aiosqlite_converted_to_sqlite(self):
        url = "sqlite+aiosqlite:///db.sqlite3"
        assert _to_sync_url(url) == "sqlite:///db.sqlite3"

    def test_aiomysql_converted_to_pymysql(self):
        url = "mysql+aiomysql://user:pass@localhost/mydb"
        assert _to_sync_url(url) == "mysql+pymysql://user:pass@localhost/mydb"

    def test_already_sync_url_passthrough(self):
        url = "sqlite:///db.sqlite3"
        assert _to_sync_url(url) == url

    def test_postgres_asyncpg_with_available_driver(self):
        """postgresql+asyncpg:// → postgresql+<driver>:// when psycopg2 available."""
        url = "postgresql+asyncpg://user:pass@localhost/mydb"
        rest = "user:pass@localhost/mydb"
        with patch("openviper.tasks.results.importlib.import_module") as mock_import:
            # Make psycopg2 importable
            mock_import.return_value = MagicMock()
            result = _to_sync_url(url)
        assert result.startswith("postgresql+")
        assert "asyncpg" not in result

    def test_postgres_asyncpg_no_sync_driver_raises(self):
        """postgresql+asyncpg:// with no sync driver available → RuntimeError."""
        url = "postgresql+asyncpg://user:pass@localhost/mydb"
        with patch(
            "openviper.tasks.results.importlib.import_module",
            side_effect=ModuleNotFoundError,
        ):
            with pytest.raises(RuntimeError, match="No synchronous PostgreSQL driver"):
                _to_sync_url(url)

    def test_postgres_prefix_variant(self):
        """postgres+asyncpg:// is also handled."""
        url = "postgres+asyncpg://user:pass@localhost/mydb"
        with patch("openviper.tasks.results.importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock()
            result = _to_sync_url(url)
        assert "asyncpg" not in result

    def test_unknown_url_passthrough(self):
        """Non-async unknown URL is returned unchanged."""
        url = "mssql+pyodbc://user:pass@localhost/mydb"
        assert _to_sync_url(url) == url


# ---------------------------------------------------------------------------
# _resolve_db_url
# ---------------------------------------------------------------------------


class TestResolveDbUrl:
    def test_reads_results_db_url_from_tasks(self):
        mock_settings = MagicMock()
        mock_settings.TASKS = {"results_db_url": "sqlite:///results.db"}
        with patch("openviper.conf.settings", mock_settings):
            url = _resolve_db_url()
        assert url == "sqlite:///results.db"

    def test_falls_back_to_database_url(self):
        mock_settings = MagicMock()
        mock_settings.TASKS = {}
        mock_settings.DATABASE_URL = "sqlite:///main.db"
        with patch("openviper.conf.settings", mock_settings):
            url = _resolve_db_url()
        assert url == "sqlite:///main.db"

    def test_returns_empty_string_on_exception(self):
        class _BadSettings:
            @property
            def TASKS(self):
                raise RuntimeError("broken")

        with patch("openviper.conf.settings", _BadSettings()):
            url = _resolve_db_url()
        assert url == ""


# ---------------------------------------------------------------------------
# reset_engine
# ---------------------------------------------------------------------------


class TestResetEngine:
    def test_resets_engine_and_upsert_fn(self):
        from sqlalchemy import create_engine as ce
        from sqlalchemy.pool import StaticPool

        engine = ce(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        results_module._metadata.create_all(engine, checkfirst=True)
        results_module._engine = engine
        results_module._upsert_fn = results_module._build_upsert_fn("sqlite")

        assert results_module._engine is not None
        reset_engine()
        assert results_module._engine is None
        assert results_module._upsert_fn is None

    def test_reset_when_no_engine_is_noop(self):
        # Already None (fixture resets before test)
        reset_engine()  # must not raise
        assert results_module._engine is None


# ---------------------------------------------------------------------------
# _build_upsert_fn — dialect detection
# ---------------------------------------------------------------------------


class TestBuildUpsertFn:
    def _make_conn(self):
        """Return a mock SQLAlchemy connection."""
        conn = MagicMock()
        return conn

    def test_sqlite_dialect_returns_callable(self):
        fn = _build_upsert_fn("sqlite")
        assert callable(fn)

    def test_postgresql_dialect_returns_callable(self):
        fn = _build_upsert_fn("postgresql")
        assert callable(fn)

    def test_mysql_dialect_returns_callable(self):
        fn = _build_upsert_fn("mysql")
        assert callable(fn)

    def test_mariadb_dialect_returns_callable(self):
        fn = _build_upsert_fn("mariadb")
        assert callable(fn)

    def test_generic_dialect_returns_callable(self):
        fn = _build_upsert_fn("unknown_dialect")
        assert callable(fn)


# ---------------------------------------------------------------------------
# Integration tests using an in-memory SQLite engine
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    """Create an in-memory SQLite engine directly (avoids pool kwargs issues)."""
    from sqlalchemy import create_engine as ce
    from sqlalchemy.pool import StaticPool

    reset_engine()
    engine = ce(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    results_module._metadata.create_all(engine, checkfirst=True)
    results_module._engine = engine
    results_module._upsert_fn = results_module._build_upsert_fn("sqlite")
    yield engine
    reset_engine()


class TestUpsertResult:
    def test_upsert_creates_new_row(self, sqlite_engine):
        upsert_result("msg-001", status="pending", actor_name="my_task")
        row = get_task_result_sync("msg-001")
        assert row is not None
        assert row["status"] == "pending"
        assert row["actor_name"] == "my_task"

    def test_upsert_updates_existing_row(self, sqlite_engine):
        upsert_result("msg-002", status="pending", actor_name="my_task")
        upsert_result("msg-002", status="success")
        row = get_task_result_sync("msg-002")
        assert row["status"] == "success"

    def test_upsert_serialises_dict_args(self, sqlite_engine):
        upsert_result("msg-003", args=[1, 2, 3], kwargs={"flag": True})
        row = get_task_result_sync("msg-003")
        assert row is not None
        assert row["args"] == [1, 2, 3]
        assert row["kwargs"] == {"flag": True}

    def test_upsert_skipped_when_no_db_url(self, caplog):
        """When engine can't be created, upsert_result logs and returns silently."""
        import logging

        reset_engine()
        with patch("openviper.tasks.results._resolve_db_url", return_value=""):
            with caplog.at_level(logging.DEBUG, logger="openviper.tasks"):
                upsert_result("msg-no-db", status="pending")
        # Must not raise; logs debug message
        assert results_module._engine is None


class TestBatchUpsertResults:
    def test_batch_empty_events_noop(self, sqlite_engine):
        batch_upsert_results([])  # must not raise

    def test_batch_creates_multiple_rows(self, sqlite_engine):
        events = [
            ("msg-b001", {"status": "success", "actor_name": "task_a"}),
            ("msg-b002", {"status": "failure", "actor_name": "task_b"}),
        ]
        batch_upsert_results(events)
        r1 = get_task_result_sync("msg-b001")
        r2 = get_task_result_sync("msg-b002")
        assert r1["status"] == "success"
        assert r2["status"] == "failure"

    def test_batch_skipped_when_no_engine(self):
        reset_engine()
        with patch("openviper.tasks.results._resolve_db_url", return_value=""):
            batch_upsert_results([("msg-xxx", {"status": "pending"})])


class TestGetTaskResultSync:
    def test_returns_none_when_not_found(self, sqlite_engine):
        row = get_task_result_sync("nonexistent-id")
        assert row is None

    def test_returns_dict_when_found(self, sqlite_engine):
        upsert_result("msg-r001", status="success", actor_name="reader_task")
        row = get_task_result_sync("msg-r001")
        assert row is not None
        assert row["message_id"] == "msg-r001"

    def test_returns_none_when_no_engine(self):
        reset_engine()
        with patch("openviper.tasks.results._resolve_db_url", return_value=""):
            result = get_task_result_sync("missing")
        assert result is None


class TestListTaskResultsSync:
    def test_returns_empty_list_when_none(self, sqlite_engine):
        rows = list_task_results_sync()
        assert isinstance(rows, list)

    def test_filters_by_status(self, sqlite_engine):
        upsert_result("msg-l001", status="success", actor_name="t1")
        upsert_result("msg-l002", status="failure", actor_name="t2")
        rows = list_task_results_sync(status="success")
        assert all(r["status"] == "success" for r in rows)

    def test_filters_by_actor_name(self, sqlite_engine):
        upsert_result("msg-l003", status="pending", actor_name="unique_actor")
        rows = list_task_results_sync(actor_name="unique_actor")
        assert all(r["actor_name"] == "unique_actor" for r in rows)

    def test_returns_empty_when_no_engine(self):
        reset_engine()
        with patch("openviper.tasks.results._resolve_db_url", return_value=""):
            rows = list_task_results_sync()
        assert rows == []


class TestAsyncWrappers:
    def test_get_task_result_async(self, sqlite_engine):
        upsert_result("msg-async-001", status="success")

        async def _run():
            return await get_task_result("msg-async-001")

        row = asyncio.run(_run())
        assert row is not None
        assert row["status"] == "success"

    def test_list_task_results_async(self, sqlite_engine):
        upsert_result("msg-async-002", status="failure")

        async def _run():
            return await list_task_results(status="failure")

        rows = asyncio.run(_run())
        assert any(r["message_id"] == "msg-async-002" for r in rows)


# ---------------------------------------------------------------------------
# _row_to_dict
# ---------------------------------------------------------------------------


class TestRowToDict:
    def _make_row(self, **kwargs):
        """Build a fake row object with a ._mapping dict."""
        row = MagicMock()
        row._mapping = kwargs
        return row

    def test_json_args_deserialized(self):
        row = self._make_row(
            message_id="x",
            status="success",
            args="[1, 2, 3]",
            kwargs='{"k": "v"}',
            enqueued_at=None,
            started_at=None,
            completed_at=None,
        )
        d = _row_to_dict(row)
        assert d["args"] == [1, 2, 3]
        assert d["kwargs"] == {"k": "v"}

    def test_invalid_json_args_left_as_string(self):
        row = self._make_row(
            message_id="x",
            status="success",
            args="not_json",
            kwargs=None,
            enqueued_at=None,
            started_at=None,
            completed_at=None,
        )
        d = _row_to_dict(row)
        assert d["args"] == "not_json"

    def test_datetime_columns_normalized_to_iso(self):
        now = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        row = self._make_row(
            message_id="x",
            status="success",
            args=None,
            kwargs=None,
            enqueued_at=now,
            started_at=None,
            completed_at=None,
        )
        d = _row_to_dict(row)
        assert d["enqueued_at"] == now.isoformat()

    def test_none_datetime_left_as_none(self):
        row = self._make_row(
            message_id="x",
            status="success",
            args=None,
            kwargs=None,
            enqueued_at=None,
            started_at=None,
            completed_at=None,
        )
        d = _row_to_dict(row)
        assert d["enqueued_at"] is None
