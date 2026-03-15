"""Unit tests for missing branches in openviper.tasks.results."""

import builtins
from unittest.mock import MagicMock, Mock, patch

import pytest

import openviper.tasks.results as results_module
from openviper.tasks.results import (
    _build_upsert_fn,
    _get_engine,
    _resolve_db_url,
    batch_upsert_results,
    delete_task_result,
    get_task_result_sync,
    get_task_stats,
    list_task_results_sync,
    reset_engine,
    setup_cleanup_task,
    shutdown_async_executor,
    upsert_result,
)


class TestGetEngineDoubleCheckLocking:
    """Test double-check locking pattern in _get_engine."""

    def test_second_thread_finds_engine_already_created(self):
        """Second thread entering lock should find _engine already set."""
        reset_engine()

        call_count = 0

        def mock_create_engine_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: simulate another thread creating the engine

                mock_engine = MagicMock()
                mock_engine.dialect.name = "sqlite"
                results_module._engine = mock_engine
                results_module._upsert_fn = lambda *a: None
                return mock_engine
            # Shouldn't get here in normal flow
            return MagicMock()

        with patch("openviper.tasks.results._resolve_db_url", return_value="sqlite:///test.db"):
            with patch("openviper.tasks.results.create_engine") as mock_create:
                mock_create.side_effect = mock_create_engine_once

                engine = _get_engine()

                # Should have called create_engine only once
                assert mock_create.call_count == 1
                assert engine is not None


class TestResolveDbUrlExceptionHandling:
    """Test exception handling in _resolve_db_url."""

    def test_returns_empty_string_on_import_error(self):
        """Should return empty string if settings import fails."""

        def mock_import(name, *args, **kwargs):
            if name == "openviper.conf":
                raise ImportError("No module")
            return Mock()

        with patch("builtins.__import__", side_effect=mock_import):
            result = _resolve_db_url()

            assert result == ""

    def test_returns_empty_string_on_attribute_error(self):
        """Should return empty string if accessing settings raises error."""
        # Create a module that raises an error when accessing TASKS
        MagicMock()

        def side_effect_getattr(name, default=None):
            if name == "TASKS":
                raise AttributeError("No TASKS")
            return default

        # Patch getattr to raise an exception
        with patch("builtins.getattr", side_effect=side_effect_getattr):
            result = _resolve_db_url()

            assert result == ""

    def test_returns_empty_string_on_generic_exception(self):
        """Should return empty string on any exception."""
        # Patch at the conf.settings module level

        def mock_import(name, *args, **kwargs):
            if name == "openviper.conf":
                raise RuntimeError("Unexpected error")
            # Call the real __import__ for other modules

            return builtins.__import__.__wrapped__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = _resolve_db_url()

            assert result == ""


class TestShutdownAsyncExecutor:
    """Test shutdown_async_executor function."""

    def test_shuts_down_executor_with_wait(self):
        """Should call shutdown with wait=True by default."""
        with patch("openviper.tasks.results._async_executor") as mock_executor:
            shutdown_async_executor()

            mock_executor.shutdown.assert_called_once_with(wait=True)

    def test_shuts_down_executor_without_wait(self):
        """Should call shutdown with wait=False when specified."""
        with patch("openviper.tasks.results._async_executor") as mock_executor:
            shutdown_async_executor(wait=False)

            mock_executor.shutdown.assert_called_once_with(wait=False)


class TestBuildUpsertFnEmptyUpdateBranches:
    """Test _build_upsert_fn branches with empty update_data."""

    def test_postgresql_with_empty_update_data(self):
        """PostgreSQL should use on_conflict_do_nothing when no update data."""
        upsert_fn = _build_upsert_fn("postgresql")

        mock_conn = MagicMock()

        # Call with empty fields (only message_id matters)
        upsert_fn(mock_conn, "test-msg-id", {})

        # Should have called execute
        assert mock_conn.execute.called

    def test_sqlite_with_empty_update_data(self):
        """SQLite should use on_conflict_do_nothing when no update data."""
        upsert_fn = _build_upsert_fn("sqlite")

        mock_conn = MagicMock()

        upsert_fn(mock_conn, "test-msg-id", {})

        assert mock_conn.execute.called

    def test_mysql_with_empty_update_data(self):
        """MySQL should use INSERT IGNORE when no update data."""
        upsert_fn = _build_upsert_fn("mysql")

        mock_conn = MagicMock()

        upsert_fn(mock_conn, "test-msg-id", {})

        assert mock_conn.execute.called

    def test_mysql_with_update_data(self):
        """MySQL should use ON DUPLICATE KEY UPDATE when update data provided."""
        upsert_fn = _build_upsert_fn("mysql")

        mock_conn = MagicMock()

        upsert_fn(mock_conn, "test-msg-id", {"status": "success", "result": "done"})

        assert mock_conn.execute.called

    def test_mariadb_with_empty_update_data(self):
        """MariaDB should use INSERT IGNORE when no update data."""
        upsert_fn = _build_upsert_fn("mariadb")

        mock_conn = MagicMock()

        upsert_fn(mock_conn, "test-msg-id", {})

        assert mock_conn.execute.called

    def test_mariadb_with_update_data(self):
        """MariaDB should use ON DUPLICATE KEY UPDATE when update data provided."""
        upsert_fn = _build_upsert_fn("mariadb")

        mock_conn = MagicMock()

        upsert_fn(mock_conn, "test-msg-id", {"status": "success"})

        assert mock_conn.execute.called

    def test_generic_with_update_data_updates_existing_row(self):
        """Generic fallback should UPDATE existing row when update_data provided."""
        upsert_fn = _build_upsert_fn("unknown_dialect")

        mock_conn = MagicMock()
        # Simulate row exists
        mock_row = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        upsert_fn(mock_conn, "test-msg-id", {"status": "success", "result": "done"})

        # Should call execute twice: once for SELECT, once for UPDATE
        assert mock_conn.execute.call_count == 2

    def test_generic_inserts_new_row_when_not_found(self):
        """Generic fallback should INSERT when row doesn't exist."""
        upsert_fn = _build_upsert_fn("unknown_dialect")

        mock_conn = MagicMock()
        # Simulate row doesn't exist
        mock_conn.execute.return_value.fetchone.return_value = None

        upsert_fn(mock_conn, "test-msg-id", {"result": "test result"})

        # Should call execute twice: once for SELECT, once for INSERT
        assert mock_conn.execute.call_count == 2


class TestUpsertResultJsonSerializationError:
    """Test upsert_result JSON serialization error handling."""

    def test_falls_back_to_repr_on_json_error(self):
        """Should use repr() if json.dumps() fails."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        mock_upsert_fn = MagicMock()

        # Create an object that can't be JSON-serialized
        class UnserializableObject:
            def __repr__(self):
                return "<UnserializableObject>"

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            with patch("openviper.tasks.results._upsert_fn", mock_upsert_fn):
                upsert_result("test-123", args=UnserializableObject())

                call_args = mock_upsert_fn.call_args[0][2]
                # Should have fallen back to repr()
                assert call_args["args"] == "<UnserializableObject>"


class TestBatchUpsertResultsExceptionHandling:
    """Test batch_upsert_results exception handling."""

    def test_handles_engine_error(self):
        """Should log and return on engine retrieval error."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            events = [("msg1", {"status": "success"})]

            # Should not raise
            batch_upsert_results(events)

    def test_handles_json_serialization_error(self):
        """Should use repr() if json.dumps() fails in batch operation."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        mock_upsert_fn = MagicMock()

        class UnserializableObject:
            def __repr__(self):
                return "<Unserializable>"

        events = [("msg1", {"args": UnserializableObject()})]

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            with patch("openviper.tasks.results._upsert_fn", mock_upsert_fn):
                batch_upsert_results(events)

                call_args = mock_upsert_fn.call_args[0][2]
                assert call_args["args"] == "<Unserializable>"

    def test_handles_batch_execution_error(self):
        """Should suppress and log errors during batch execution."""
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = Exception("Database error")

        events = [("msg1", {"status": "success"})]

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            # Should not raise
            batch_upsert_results(events)


class TestGetTaskResultSyncExceptionHandling:
    """Test get_task_result_sync exception handling."""

    def test_returns_none_on_engine_error(self):
        """Should return None if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            result = get_task_result_sync("test-123")

            assert result is None


class TestListTaskResultsSyncAdditionalFilters:
    """Test list_task_results_sync with actor_name and queue_name filters."""

    def _make_engine(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        return mock_engine, mock_conn

    def test_filters_by_actor_name(self):
        """Should filter by actor_name when provided."""
        mock_engine, mock_conn = self._make_engine()

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            list_task_results_sync(actor_name="my_actor")

            # Should execute query without error
            mock_conn.execute.return_value.fetchall.assert_called_once()

    def test_filters_by_queue_name(self):
        """Should filter by queue_name when provided."""
        mock_engine, mock_conn = self._make_engine()

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            list_task_results_sync(queue_name="my_queue")

            mock_conn.execute.return_value.fetchall.assert_called_once()

    def test_filters_by_all_parameters(self):
        """Should filter by status, actor_name, and queue_name together."""
        mock_engine, mock_conn = self._make_engine()

        with patch("openviper.tasks.results._get_engine", return_value=mock_engine):
            list_task_results_sync(
                status="success",
                actor_name="my_actor",
                queue_name="my_queue",
            )

            mock_conn.execute.return_value.fetchall.assert_called_once()

    def test_returns_empty_list_on_engine_error(self):
        """Should return empty list if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            results = list_task_results_sync()

            assert results == []


class TestDeleteTaskResultExceptionHandling:
    """Test delete_task_result exception handling."""

    def test_returns_false_on_engine_error(self):
        """Should return False if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            result = delete_task_result("test-123")

            assert result is False


@pytest.mark.asyncio
class TestGetTaskStatsExceptionHandling:
    """Test get_task_stats exception handling."""

    async def test_returns_zero_stats_on_engine_error(self):
        """Should return zero stats if engine retrieval fails."""
        with patch("openviper.tasks.results._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = RuntimeError("No DB")

            stats = await get_task_stats()

            assert stats == {
                "total": 0,
                "success": 0,
                "failure": 0,
                "pending": 0,
                "running": 0,
            }


class TestSetupCleanupTask:
    """Test setup_cleanup_task function."""

    def test_handles_import_error(self):
        """Should suppress and log error if imports fail."""

        def mock_import(name, *args, **kwargs):
            if "openviper.conf" in name:
                raise ImportError("No module")

            return builtins.__import__.__wrapped__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import, wraps=__import__):
            # Should not raise
            setup_cleanup_task()

    def test_handles_generic_exception(self):
        """Should suppress and log error on any exception during setup."""

        def mock_import(name, *args, **kwargs):
            if "openviper.conf" in name:
                raise RuntimeError("Unexpected error")

            return builtins.__import__.__wrapped__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import, wraps=__import__):
            # Should not raise
            setup_cleanup_task()
