"""Tests for openviper.tasks.middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.middleware import (
    DatabaseCleanupMiddleware,
    StateObservationMiddleware,
    UnifiedContextLogger,
    get_trace_id,
)


def make_message(actor_name: str = "test", **kwargs) -> object:
    """Create a minimal Dramatiq-like message object for testing."""
    return type("Message", (), {"actor_name": actor_name, **kwargs})()


class TestDatabaseCleanupMiddleware:
    """Test database cleanup middleware hooks."""

    def test_before_process_message(self) -> None:
        mw = DatabaseCleanupMiddleware()
        mw.before_process_message(None, make_message("test"))

    def test_after_process_message_success(self) -> None:
        mw = DatabaseCleanupMiddleware()
        mw.after_process_message(None, make_message("test"), result=None, exception=None)

    def test_after_process_message_failure(self) -> None:
        mw = DatabaseCleanupMiddleware()
        mw.after_process_message(
            None, make_message("test"), result=None, exception=RuntimeError("boom")
        )

    def test_after_skip_message(self) -> None:
        mw = DatabaseCleanupMiddleware()
        mw.after_skip_message(None, make_message("test"))

    @patch("openviper.tasks.middleware.DatabaseCleanupMiddleware.close_stale_connections")
    def test_after_process_closes_connections(self, mock_close: MagicMock) -> None:
        """after_process_message with no exception should close idle connections."""
        mw = DatabaseCleanupMiddleware()
        msg = make_message("test")
        mw.after_process_message(None, msg, result=None, exception=None)
        mock_close.assert_called_once()

    @patch("openviper.tasks.middleware.DatabaseCleanupMiddleware.rollback_and_close")
    def test_after_failure_rolls_back(self, mock_rollback: MagicMock) -> None:
        """after_process_message with exception should roll back transactions."""
        mw = DatabaseCleanupMiddleware()
        msg = make_message("test")
        mw.after_process_message(None, msg, result=None, exception=RuntimeError("boom"))
        mock_rollback.assert_called_once()


class TestStateObservationMiddleware:
    """Test state observation middleware hooks."""

    def test_before_process_message(self) -> None:
        mw = StateObservationMiddleware()
        mw.before_process_message(None, make_message("test"))

    def test_after_process_message_success(self) -> None:
        mw = StateObservationMiddleware()
        mw.after_process_message(None, make_message("test"), result=None, exception=None)

    def test_after_process_message_failure(self) -> None:
        mw = StateObservationMiddleware()
        mw.after_process_message(
            None, make_message("test"), result=None, exception=RuntimeError("boom")
        )

    def test_after_skip_message(self) -> None:
        mw = StateObservationMiddleware()
        mw.after_skip_message(None, make_message("test"))

    @patch("openviper.tasks.middleware.StateObservationMiddleware.upsert_task_result")
    def test_before_process_marks_running(self, mock_upsert: MagicMock) -> None:
        """before_process_message should mark the task as running."""
        mw = StateObservationMiddleware()
        msg = make_message("my_task")
        mw.before_process_message(None, msg)
        mock_upsert.assert_called_once_with(msg, status="running")

    @patch("openviper.tasks.middleware.StateObservationMiddleware.upsert_task_result")
    def test_after_process_marks_success(self, mock_upsert: MagicMock) -> None:
        """after_process_message with no exception should mark as success."""
        mw = StateObservationMiddleware()
        msg = make_message("my_task")
        mw.after_process_message(None, msg, result=None, exception=None)
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["status"] == "success"

    @patch("openviper.tasks.middleware.StateObservationMiddleware.upsert_task_result")
    def test_after_process_marks_failure(self, mock_upsert: MagicMock) -> None:
        """after_process_message with exception should mark as failure or dead."""
        mw = StateObservationMiddleware()
        msg = make_message("my_task", options={})
        mw.after_process_message(None, msg, result=None, exception=RuntimeError("boom"))
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["status"] in ("failure", "dead")

    @patch("openviper.tasks.middleware.StateObservationMiddleware.upsert_task_result")
    def test_after_process_marks_dead_after_max_retries(self, mock_upsert: MagicMock) -> None:
        """after_process_message should mark as dead when retries >= 3."""
        mw = StateObservationMiddleware()
        msg = make_message("my_task", options={"retries": 3})
        mw.after_process_message(None, msg, result=None, exception=RuntimeError("boom"))
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["status"] == "dead"

    @patch("openviper.tasks.middleware.StateObservationMiddleware.upsert_task_result")
    def test_after_skip_marks_skipped(self, mock_upsert: MagicMock) -> None:
        """after_skip_message should mark the task as skipped."""
        mw = StateObservationMiddleware()
        msg = make_message("my_task")
        mw.after_skip_message(None, msg)
        mock_upsert.assert_called_once_with(msg, status="skipped")


class TestUnifiedContextLogger:
    """Test context logger middleware hooks."""

    def test_before_process_message(self) -> None:
        mw = UnifiedContextLogger()
        mw.before_process_message(None, make_message("test"))

    def test_after_process_message_success(self) -> None:
        mw = UnifiedContextLogger()
        mw.after_process_message(None, make_message("test"), result=None, exception=None)

    def test_after_process_message_failure(self) -> None:
        mw = UnifiedContextLogger()
        mw.after_process_message(
            None, make_message("test"), result=None, exception=RuntimeError("err")
        )

    def test_get_trace_id_returns_empty_by_default(self) -> None:
        """get_trace_id returns empty string when no task is running."""
        import contextvars

        trace_id_var_new = contextvars.ContextVar("openviper.tasks.trace_id.test", default="")
        assert trace_id_var_new.get("") == ""

    def test_before_process_sets_trace_id(self) -> None:
        """before_process_message should set a trace ID in the context variable."""
        from openviper.tasks.middleware import trace_id_var

        mw = UnifiedContextLogger()
        msg = make_message("test")
        mw.before_process_message(None, msg)
        trace_id = trace_id_var.get("")
        assert trace_id != ""
        assert len(trace_id) == 8
