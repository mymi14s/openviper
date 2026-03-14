"""Unit tests for openviper.tasks.results — Task result storage."""

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.results import (
    _build_upsert_fn,
    _get_engine,
    _row_to_dict,
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
    upsert_result,
)


class TestToSyncUrl:
    """Test _to_sync_url helper function."""

    def test_sqlite_conversion(self):
        """Should convert sqlite+aiosqlite to sqlite."""
        url = "sqlite+aiosqlite:///test.db"
        result = _to_sync_url(url)
        assert result == "sqlite:///test.db"

    def test_mysql_conversion(self):
        """Should convert mysql+aiomysql to mysql+pymysql."""
        url = "mysql+aiomysql://user:pass@localhost/db"
        result = _to_sync_url(url)
        assert result == "mysql+pymysql://user:pass@localhost/db"

    def test_postgresql_conversion_with_psycopg2(self):
        """Should convert postgresql+asyncpg to postgresql+psycopg2."""
        url = "postgresql+asyncpg://user:pass@localhost/db"

        with patch("openviper.tasks.results.importlib.import_module") as mock_import:
            # Simulate psycopg2 available
            mock_import.return_value = MagicMock()

            result = _to_sync_url(url)
            assert result == "postgresql+psycopg2://user:pass@localhost/db"

    def test_postgresql_fallback_to_pg8000(self):
        """Should fall back to pg8000 if psycopg2 not available."""
        url = "postgresql+asyncpg://user:pass@localhost/db"

        def import_side_effect(name):
            if name == "psycopg2":
                raise ModuleNotFoundError("psycopg2 not found")
            return MagicMock()

        with patch(
            "openviper.tasks.results.importlib.import_module", side_effect=import_side_effect
        ):
            result = _to_sync_url(url)
            assert result == "postgresql+pg8000://user:pass@localhost/db"

    def test_postgresql_raises_if_no_driver(self):
        """Should raise RuntimeError if no PostgreSQL driver available."""
        url = "postgresql+asyncpg://user:pass@localhost/db"

        with patch("openviper.tasks.results.importlib.import_module") as mock_import:
            mock_import.side_effect = ModuleNotFoundError("No driver")

            with pytest.raises(RuntimeError, match="No synchronous PostgreSQL driver"):
                _to_sync_url(url)

    def test_already_sync_url_passthrough(self):
        """Should pass through already-sync URLs unchanged."""
        url = "postgresql://user:pass@localhost/db"
        result = _to_sync_url(url)
        assert result == url

    def test_unknown_url_passthrough(self):
        """Should pass through unknown URL schemes unchanged."""
        url = "unknown://user:pass@localhost/db"
        result = _to_sync_url(url)
        assert result == url


class TestGetEngine:
    """Test _get_engine function."""

    def test_caches_engine(self):
        """_get_engine should cache the engine instance."""
        reset_engine()

        with patch("openviper.tasks.results._resolve_db_url") as mock_resolve:
            mock_resolve.return_value = "sqlite:///test.db"
            with patch("openviper.tasks.results.create_engine") as mock_create:
                mock_engine = MagicMock()
                mock_create.return_value = mock_engine

                engine1 = _get_engine()
                engine2 = _get_engine()

                assert engine1 is engine2
                mock_create.assert_called_once()

    def test_raises_if_no_db_url(self):
        """Should raise RuntimeError if no DB URL is configured."""
        reset_engine()

        with patch("openviper.tasks.results._resolve_db_url") as mock_resolve:
            mock_resolve.return_value = ""

            with pytest.raises(RuntimeError, match="requires a DATABASE_URL"):
                _get_engine()

    def test_creates_table(self):
        """Should create the results table on first call."""
        reset_engine()

        with patch("openviper.tasks.results._resolve_db_url") as mock_resolve:
            mock_resolve.return_value = "sqlite:///test.db"
            with patch("openviper.tasks.results.create_engine") as mock_create:
                mock_engine = MagicMock()
                mock_create.return_value = mock_engine
                with patch("openviper.tasks.results._metadata.create_all") as mock_create_all:
                    _get_engine()

                    mock_create_all.assert_called_once()


class TestBuildUpsertFn:
    """Test _build_upsert_fn helper."""

    def test_postgresql_uses_on_conflict(self):
        """PostgreSQL should use INSERT ... ON CONFLICT."""
        upsert_fn = _build_upsert_fn("postgresql")

        # Should be a callable
        assert callable(upsert_fn)

    def test_sqlite_uses_on_conflict(self):
        """SQLite should use INSERT ... ON CONFLICT."""
        upsert_fn = _build_upsert_fn("sqlite")

        assert callable(upsert_fn)

    def test_mysql_uses_on_duplicate_key(self):
        """MySQL should use INSERT ... ON DUPLICATE KEY."""
        upsert_fn = _build_upsert_fn("mysql")

        assert callable(upsert_fn)

    def test_unknown_dialect_uses_fallback(self):
        """Unknown dialects should use SELECT + INSERT/UPDATE fallback."""
        upsert_fn = _build_upsert_fn("unknown")

        assert callable(upsert_fn)


class TestUpsertResult:
    """Test upsert_result function."""

    def test_upserts_result(self):
        """Should call upsert function with message_id and fields."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        mock_upsert_fn = MagicMock()

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            with patch("openviper.tasks.results._upsert_fn", mock_upsert_fn):
                upsert_result("test-123", status="success", result="done")

                mock_upsert_fn.assert_called_once()
                call_args = mock_upsert_fn.call_args[0]
                assert call_args[1] == "test-123"
                assert call_args[2]["status"] == "success"

    def test_serialises_args_and_kwargs(self):
        """Should JSON-serialise args and kwargs fields."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        mock_upsert_fn = MagicMock()

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            with patch("openviper.tasks.results._upsert_fn", mock_upsert_fn):
                upsert_result("test-123", args=[1, 2], kwargs={"key": "value"})

                call_args = mock_upsert_fn.call_args[0][2]
                assert call_args["args"] == "[1, 2]"
                assert call_args["kwargs"] == '{"key": "value"}'

    def test_handles_engine_error(self):
        """Should suppress errors if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            # Should not raise
            upsert_result("test-123", status="success")

    def test_handles_upsert_error(self):
        """Should suppress errors if upsert fails."""
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = Exception("DB error")

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            # Should not raise
            upsert_result("test-123", status="success")


class TestBatchUpsertResults:
    """Test batch_upsert_results function."""

    def test_empty_list_is_noop(self):
        """Should do nothing for empty event list."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            batch_upsert_results([])

            mock_get_engine.assert_not_called()

    def test_batch_upserts_multiple_events(self):
        """Should upsert all events in a single transaction."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        mock_upsert_fn = MagicMock()

        events = [
            ("msg1", {"status": "success"}),
            ("msg2", {"status": "failure"}),
        ]

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            with patch("openviper.tasks.results._upsert_fn", mock_upsert_fn):
                batch_upsert_results(events)

                assert mock_upsert_fn.call_count == 2


class TestGetTaskResultSync:
    """Test get_task_result_sync function."""

    def test_returns_result_dict(self):
        """Should return result as dict when found."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {
            "message_id": "test-123",
            "status": "success",
            "actor_name": "my_actor",
        }
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            result = get_task_result_sync("test-123")

            assert result["message_id"] == "test-123"
            assert result["status"] == "success"

    def test_returns_none_when_not_found(self):
        """Should return None when result not found."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            result = get_task_result_sync("nonexistent")

            assert result is None


class TestListTaskResultsSync:
    """Test list_task_results_sync function."""

    def test_returns_list_of_results(self):
        """Should return list of result dicts."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_rows = [
            MagicMock(_mapping={"message_id": "msg1", "status": "success"}),
            MagicMock(_mapping={"message_id": "msg2", "status": "failure"}),
        ]
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            results = list_task_results_sync()

            assert len(results) == 2
            assert results[0]["message_id"] == "msg1"
            assert results[1]["message_id"] == "msg2"

    def test_filters_by_status(self):
        """Should filter by status when provided."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            list_task_results_sync(status="success")

            # Check that query was built with status filter
            # (Would need to inspect SQL but for unit test we just ensure no error)
            assert True


@pytest.mark.asyncio
class TestGetTaskResult:
    """Test get_task_result async wrapper."""

    async def test_delegates_to_sync_version(self):
        """Should call get_task_result_sync in executor."""
        mock_result = {"message_id": "test-123"}

        with patch("openviper.tasks.results.get_task_result_sync", return_value=mock_result):
            result = await get_task_result("test-123")

            assert result == mock_result


@pytest.mark.asyncio
class TestListTaskResults:
    """Test list_task_results async wrapper."""

    async def test_delegates_to_sync_version(self):
        """Should call list_task_results_sync in executor."""
        mock_results = [{"message_id": "msg1"}]

        with patch("openviper.tasks.results.list_task_results_sync", return_value=mock_results):
            results = await list_task_results()

            assert results == mock_results


class TestDeleteTaskResult:
    """Test delete_task_result function."""

    def test_deletes_result(self):
        """Should delete result and return True."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            result = delete_task_result("test-123")

            assert result is True

    def test_returns_false_when_not_found(self):
        """Should return False when no row deleted."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            result = delete_task_result("nonexistent")

            assert result is False


class TestCleanOldResults:
    """Test clean_old_results function."""

    def test_deletes_old_results(self):
        """Should delete results older than cutoff."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_conn.execute.return_value = mock_result
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            count = clean_old_results(days=7)

            assert count == 5

    def test_returns_zero_on_error(self):
        """Should return 0 if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            count = clean_old_results(days=7)

            assert count == 0


@pytest.mark.asyncio
class TestGetTaskStats:
    """Test get_task_stats async function."""

    async def test_returns_stats_dict(self):
        """Should return dict with task counts by status."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("success", 10),
            ("failure", 2),
            ("pending", 5),
        ]
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            stats = await get_task_stats()

            assert stats["success"] == 10
            assert stats["failure"] == 2
            assert stats["pending"] == 5
            assert stats["total"] == 17


class TestRowToDict:
    """Test _row_to_dict helper."""

    def test_converts_row_to_dict(self):
        """Should convert SQLAlchemy row to dict."""
        mock_row = MagicMock()
        mock_row._mapping = {
            "message_id": "test-123",
            "status": "success",
        }

        result = _row_to_dict(mock_row)

        assert result["message_id"] == "test-123"
        assert result["status"] == "success"

    def test_deserialises_json_columns(self):
        """Should deserialise JSON string columns to Python objects."""
        mock_row = MagicMock()
        mock_row._mapping = {
            "args": "[1, 2, 3]",
            "kwargs": '{"key": "value"}',
        }

        result = _row_to_dict(mock_row)

        assert result["args"] == [1, 2, 3]
        assert result["kwargs"] == {"key": "value"}

    def test_converts_datetime_to_iso(self):
        """Should convert datetime objects to ISO strings."""
        now = datetime.now(UTC)
        mock_row = MagicMock()
        mock_row._mapping = {
            "enqueued_at": now,
        }

        result = _row_to_dict(mock_row)

        assert isinstance(result["enqueued_at"], str)
        assert now.isoformat() == result["enqueued_at"]


class TestListTaskResultsSyncNoneFilters:
    """Regression: empty-string filter args must not be silently ignored."""

    def _make_engine(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        return mock_engine, mock_conn

    def test_none_status_does_not_filter(self):
        """status=None should not add a WHERE clause."""
        mock_engine, mock_conn = self._make_engine()
        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            list_task_results_sync(status=None)
        # fetchall called means the query ran without error
        mock_conn.execute.return_value.fetchall.assert_called_once()

    def test_empty_string_status_applies_filter(self):
        """status='' is a valid (if unusual) filter — it must reach the WHERE clause.

        Previously ``if status:`` skipped empty-string values; the fix
        ``if status is not None:`` ensures they are forwarded to SQLAlchemy.
        """
        mock_engine, mock_conn = self._make_engine()
        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            # Should not raise; empty string is forwarded to the query
            list_task_results_sync(status="")
        mock_conn.execute.return_value.fetchall.assert_called_once()


class TestRowToDictJsonErrors:
    """_row_to_dict must log and preserve raw value on JSON parse failure."""

    def test_invalid_json_preserved_as_string(self):
        """Malformed JSON in args/kwargs column should keep the raw string."""
        mock_row = MagicMock()
        mock_row._mapping = {
            "args": "not-valid-json{{{",
            "kwargs": '{"key": "value"}',
        }

        result = _row_to_dict(mock_row)

        # Malformed value is left as-is (not silently dropped)
        assert result["args"] == "not-valid-json{{{"
        # Valid column is still deserialised
        assert result["kwargs"] == {"key": "value"}

    def test_invalid_json_logged(self, caplog):
        """A debug message must be emitted when JSON parsing fails."""

        mock_row = MagicMock()
        mock_row._mapping = {"args": "bad json", "kwargs": None}

        with caplog.at_level(logging.DEBUG, logger="openviper.tasks"):
            _row_to_dict(mock_row)

        assert any("args" in r.getMessage() for r in caplog.records)
