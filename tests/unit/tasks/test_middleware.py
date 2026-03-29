"""Tests for openviper/tasks/middleware.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.middleware as mw_module
from openviper.tasks.middleware import (
    SchedulerMiddleware,
    TaskTrackingMiddleware,
    _EventBuffer,
    _serialise,
    _TrackingEvent,
    reset_tracking_buffer,
)


@pytest.fixture(autouse=True)
def clean_buffer():
    yield
    reset_tracking_buffer()


def _make_message(message_id: str = "msg-001", actor: str = "my_actor", queue: str = "default"):
    msg = MagicMock()
    msg.message_id = message_id
    msg.actor_name = actor
    msg.queue_name = queue
    msg.args = [1, 2]
    msg.kwargs = {"k": "v"}
    return msg


# ---------------------------------------------------------------------------
# _serialise
# ---------------------------------------------------------------------------


class TestSerialise:
    def test_none_returns_none(self) -> None:
        assert _serialise(None) is None

    def test_serializable_returns_json(self) -> None:
        result = _serialise({"key": "value"})
        assert result == json.dumps({"key": "value"})

    def test_non_serializable_returns_repr(self) -> None:
        obj = object()
        result = _serialise(obj)
        assert result == repr(obj)

    def test_string(self) -> None:
        assert _serialise("hello") == '"hello"'

    def test_integer(self) -> None:
        assert _serialise(42) == "42"


# ---------------------------------------------------------------------------
# _EventBuffer
# ---------------------------------------------------------------------------


class TestEventBuffer:
    def test_push_non_terminal_no_flush(self) -> None:
        buf = _EventBuffer(flush_threshold=5)
        with patch.object(buf._executor, "submit") as mock_submit:
            buf.push(_TrackingEvent("id1", {"status": "running"}, terminal=False))
            mock_submit.assert_not_called()

    def test_push_terminal_triggers_flush(self) -> None:
        buf = _EventBuffer(flush_threshold=5)
        submitted = []
        with patch.object(
            buf._executor, "submit", side_effect=lambda fn, evts: submitted.append(evts)
        ):
            buf.push(_TrackingEvent("id1", {"status": "success"}, terminal=True))
        assert len(submitted) == 1

    def test_threshold_triggers_flush(self) -> None:
        buf = _EventBuffer(flush_threshold=3)
        submitted = []
        with patch.object(
            buf._executor, "submit", side_effect=lambda fn, evts: submitted.append(evts)
        ):
            for i in range(3):
                buf.push(_TrackingEvent(f"id{i}", {"status": "running"}, terminal=False))
        assert len(submitted) == 1
        assert len(submitted[0]) == 3

    def test_queue_cleared_after_flush(self) -> None:
        buf = _EventBuffer(flush_threshold=2)
        with patch.object(buf._executor, "submit"):
            buf.push(_TrackingEvent("id1", {}, terminal=False))
            buf.push(_TrackingEvent("id2", {}, terminal=True))
        assert len(buf._queue) == 0

    def test_flush_calls_batch_upsert(self) -> None:
        buf = _EventBuffer(flush_threshold=10)
        events = [_TrackingEvent("id1", {"status": "success"}, terminal=True)]
        with patch("openviper.tasks.middleware.batch_upsert_results") as mock_batch:
            buf._flush(events)
        mock_batch.assert_called_once()

    def test_flush_handles_exception(self) -> None:
        buf = _EventBuffer(flush_threshold=10)
        events = [_TrackingEvent("id1", {}, terminal=True)]
        with patch(
            "openviper.tasks.middleware.batch_upsert_results", side_effect=RuntimeError("db")
        ):
            buf._flush(events)  # should not raise

    def test_shutdown(self) -> None:
        buf = _EventBuffer(flush_threshold=5)
        buf.shutdown(wait=False)  # should not raise


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware
# ---------------------------------------------------------------------------


class TestTaskTrackingMiddleware:
    def test_before_enqueue(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.before_enqueue(MagicMock(), msg, None)
        mock_push.assert_called_once()
        event = mock_push.call_args[0][0]
        assert event.message_id == "msg-001"
        assert event.fields["status"] == "pending"
        assert event.terminal is False

    def test_before_enqueue_handles_exception(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push", side_effect=RuntimeError("boom")):
            mw.before_enqueue(MagicMock(), msg, None)  # should not raise

    def test_before_process_message(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.before_process_message(MagicMock(), msg)
        mock_push.assert_called_once()
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "running"

    def test_before_process_message_handles_exception(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push", side_effect=RuntimeError("boom")):
            mw.before_process_message(MagicMock(), msg)  # should not raise

    def test_after_process_message_success(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.after_process_message(MagicMock(), msg, result="ok", exception=None)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "success"
        assert event.terminal is True

    def test_after_process_message_failure(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        exc = ValueError("task failed")
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.after_process_message(MagicMock(), msg, result=None, exception=exc)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "failure"
        assert event.terminal is True

    def test_after_process_message_handles_exception(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push", side_effect=RuntimeError("boom")):
            mw.after_process_message(MagicMock(), msg)  # should not raise

    def test_after_skip_message(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.after_skip_message(MagicMock(), msg)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "skipped"
        assert event.terminal is True

    def test_after_skip_message_handles_exception(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push", side_effect=RuntimeError("boom")):
            mw.after_skip_message(MagicMock(), msg)  # should not raise

    def test_after_nack(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push") as mock_push:
            mw.after_nack(MagicMock(), msg)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "dead"
        assert event.terminal is True

    def test_after_nack_handles_exception(self) -> None:
        mw = TaskTrackingMiddleware()
        msg = _make_message()
        with patch.object(mw_module._event_buffer, "push", side_effect=RuntimeError("boom")):
            mw.after_nack(MagicMock(), msg)  # should not raise


# ---------------------------------------------------------------------------
# SchedulerMiddleware
# ---------------------------------------------------------------------------


class TestSchedulerMiddleware:
    def test_after_worker_boot_no_error(self) -> None:
        mw = SchedulerMiddleware()
        mw.after_worker_boot(MagicMock(), MagicMock())  # should not raise

    def test_before_worker_shutdown_no_error(self) -> None:
        mw = SchedulerMiddleware()
        mw.before_worker_shutdown(MagicMock(), MagicMock())  # should not raise


# ---------------------------------------------------------------------------
# reset_tracking_buffer
# ---------------------------------------------------------------------------


class TestResetTrackingBuffer:
    def test_clears_queue(self) -> None:
        mw_module._event_buffer._queue.append(
            _TrackingEvent("id1", {"status": "running"}, terminal=False)
        )
        reset_tracking_buffer()
        assert len(mw_module._event_buffer._queue) == 0

    def test_creates_new_buffer(self) -> None:
        old_buffer = mw_module._event_buffer
        reset_tracking_buffer()
        assert mw_module._event_buffer is not old_buffer


# ---------------------------------------------------------------------------
# _get_flush_threshold
# ---------------------------------------------------------------------------


class TestGetFlushThreshold:
    def test_returns_default_on_exception(self) -> None:
        from openviper.tasks.middleware import _get_flush_threshold

        with patch("openviper.tasks.middleware.settings") as mock_settings:
            type(mock_settings).TASKS = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
            result = _get_flush_threshold()
        assert result == 20

    def test_reads_from_settings(self) -> None:
        from openviper.tasks.middleware import _get_flush_threshold

        with patch("openviper.tasks.middleware.settings") as mock_settings:
            mock_settings.TASKS = {"tracking_flush_threshold": 50}
            result = _get_flush_threshold()
        assert result == 50
