"""Unit tests for openviper.tasks.middleware — Task lifecycle tracking."""

from unittest.mock import MagicMock, patch

import pytest

import openviper.conf as _conf_module
from openviper.tasks.middleware import (
    SchedulerMiddleware,
    TaskTrackingMiddleware,
    _event_buffer,
    _EventBuffer,
    _get_flush_threshold,
    _serialise,
    _TrackingEvent,
    reset_tracking_buffer,
)


class TestTrackingEvent:
    """Test _TrackingEvent dataclass."""

    def test_creation(self):
        """_TrackingEvent should hold message_id, fields, and terminal flag."""
        event = _TrackingEvent(message_id="test-123", fields={"status": "success"}, terminal=True)

        assert event.message_id == "test-123"
        assert event.fields == {"status": "success"}
        assert event.terminal is True


class TestEventBuffer:
    """Test _EventBuffer class."""

    def test_push_non_terminal_event(self):
        """Pushing a non-terminal event should buffer it."""
        buffer = _EventBuffer(flush_threshold=10)
        event = _TrackingEvent(message_id="test-123", fields={"status": "pending"}, terminal=False)

        with patch.object(buffer, "_flush") as mock_flush:
            buffer.push(event)

            # Should not flush immediately
            mock_flush.assert_not_called()

    def test_push_terminal_event_flushes(self):
        """Pushing a terminal event should trigger immediate flush."""
        buffer = _EventBuffer(flush_threshold=10)
        event = _TrackingEvent(message_id="test-123", fields={"status": "success"}, terminal=True)

        with patch.object(buffer._executor, "submit") as mock_submit:
            buffer.push(event)

            # Should submit flush task
            mock_submit.assert_called_once()

    def test_push_threshold_reached_flushes(self):
        """Buffering threshold events should trigger flush."""
        buffer = _EventBuffer(flush_threshold=2)

        event1 = _TrackingEvent("msg1", {"status": "pending"}, terminal=False)
        event2 = _TrackingEvent("msg2", {"status": "pending"}, terminal=False)

        with patch.object(buffer._executor, "submit") as mock_submit:
            buffer.push(event1)
            assert mock_submit.call_count == 0

            buffer.push(event2)
            # Should flush after reaching threshold
            assert mock_submit.call_count == 1

    def test_flush_calls_batch_upsert(self):
        """_flush should call batch_upsert_results."""
        buffer = _EventBuffer()
        events = [
            _TrackingEvent("msg1", {"status": "success"}, terminal=True),
            _TrackingEvent("msg2", {"status": "failure"}, terminal=True),
        ]

        with patch("openviper.tasks.middleware.batch_upsert_results") as mock_upsert:
            buffer._flush(events)

            mock_upsert.assert_called_once()
            call_args = mock_upsert.call_args[0][0]
            assert len(call_args) == 2
            assert call_args[0][0] == "msg1"
            assert call_args[1][0] == "msg2"

    def test_flush_handles_errors(self):
        """_flush should not raise if batch_upsert_results fails."""
        buffer = _EventBuffer()
        events = [_TrackingEvent("msg1", {"status": "success"}, terminal=True)]

        with patch("openviper.tasks.middleware.batch_upsert_results") as mock_upsert:
            mock_upsert.side_effect = Exception("DB error")

            # Should not raise
            buffer._flush(events)

    def test_shutdown(self):
        """shutdown should stop the executor."""
        buffer = _EventBuffer()

        with patch.object(buffer._executor, "shutdown") as mock_shutdown:
            buffer.shutdown(wait=True)

            mock_shutdown.assert_called_once_with(wait=True)


class TestResetTrackingBuffer:
    """Test reset_tracking_buffer function."""

    def test_clears_buffer(self):
        """reset_tracking_buffer should clear the event queue."""

        # Add an event
        event = _TrackingEvent("test", {"status": "pending"}, terminal=False)
        _event_buffer.push(event)

        reset_tracking_buffer()

        # Queue should be empty
        assert len(_event_buffer._queue) == 0

    def test_shutdowns_executor(self):
        """reset_tracking_buffer should shutdown the executor."""
        reset_tracking_buffer()

        # After reset, a new buffer should exist
        assert _event_buffer._executor is not None


class TestTaskTrackingMiddleware:
    """Test TaskTrackingMiddleware hooks."""

    @pytest.fixture
    def middleware(self):
        """Create a TaskTrackingMiddleware instance."""
        return TaskTrackingMiddleware()

    @pytest.fixture
    def mock_message(self):
        """Create a mock Dramatiq message."""
        msg = MagicMock()
        msg.message_id = "test-msg-123"
        msg.actor_name = "test_actor"
        msg.queue_name = "default"
        msg.args = (1, 2)
        msg.kwargs = {"key": "value"}
        return msg

    def test_before_enqueue(self, middleware, mock_message):
        """before_enqueue should push a pending event."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.before_enqueue(broker, mock_message, delay=None)

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.message_id == "test-msg-123"
            assert event.fields["status"] == "pending"
            assert event.fields["actor_name"] == "test_actor"
            assert event.terminal is False

    def test_before_process_message(self, middleware, mock_message):
        """before_process_message should push a running event."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.before_process_message(broker, mock_message)

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.fields["status"] == "running"
            assert "started_at" in event.fields
            assert event.terminal is False

    def test_after_process_message_success(self, middleware, mock_message):
        """after_process_message should push a success event when no exception."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.after_process_message(
                broker, mock_message, result="success_result", exception=None
            )

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.fields["status"] == "success"
            assert "completed_at" in event.fields
            assert event.terminal is True

    def test_after_process_message_failure(self, middleware, mock_message):
        """after_process_message should push a failure event when exception occurs."""
        broker = MagicMock()
        exception = ValueError("Task failed")

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.after_process_message(broker, mock_message, result=None, exception=exception)

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.fields["status"] == "failure"
            assert event.fields["error"] == "Task failed"
            assert "traceback" in event.fields
            assert event.terminal is True

    def test_after_skip_message(self, middleware, mock_message):
        """after_skip_message should push a skipped event."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.after_skip_message(broker, mock_message)

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.fields["status"] == "skipped"
            assert event.terminal is True

    def test_after_nack(self, middleware, mock_message):
        """after_nack should push a dead event."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            middleware.after_nack(broker, mock_message)

            mock_buffer.push.assert_called_once()
            event = mock_buffer.push.call_args[0][0]
            assert event.fields["status"] == "dead"
            assert event.terminal is True

    def test_hooks_suppress_errors(self, middleware, mock_message):
        """All hooks should suppress errors to avoid killing worker."""
        broker = MagicMock()

        with patch("openviper.tasks.middleware._event_buffer") as mock_buffer:
            mock_buffer.push.side_effect = Exception("Buffer error")

            # Should not raise
            middleware.before_enqueue(broker, mock_message, delay=None)
            middleware.before_process_message(broker, mock_message)
            middleware.after_process_message(broker, mock_message, result=None, exception=None)
            middleware.after_skip_message(broker, mock_message)
            middleware.after_nack(broker, mock_message)


class TestSchedulerMiddleware:
    """Test SchedulerMiddleware hooks."""

    @pytest.fixture
    def middleware(self):
        """Create a SchedulerMiddleware instance."""
        return SchedulerMiddleware()

    def test_after_worker_boot_starts_scheduler(self, middleware):
        """after_worker_boot should start the scheduler."""
        broker = MagicMock()
        worker = MagicMock()

        with patch("openviper.tasks.middleware.start_scheduler") as mock_start:
            middleware.after_worker_boot(broker, worker)

            mock_start.assert_called_once()

    def test_after_worker_boot_handles_error(self, middleware):
        """after_worker_boot should suppress errors."""
        broker = MagicMock()
        worker = MagicMock()

        with patch("openviper.tasks.middleware.start_scheduler") as mock_start:
            mock_start.side_effect = Exception("Start failed")

            # Should not raise
            middleware.after_worker_boot(broker, worker)

    def test_before_worker_shutdown_stops_scheduler(self, middleware):
        """before_worker_shutdown should stop the scheduler."""
        broker = MagicMock()
        worker = MagicMock()

        with patch("openviper.tasks.middleware.stop_scheduler") as mock_stop:
            middleware.before_worker_shutdown(broker, worker)

            mock_stop.assert_called_once()

    def test_before_worker_shutdown_handles_error(self, middleware):
        """before_worker_shutdown should suppress errors."""
        broker = MagicMock()
        worker = MagicMock()

        with patch("openviper.tasks.middleware.stop_scheduler") as mock_stop:
            mock_stop.side_effect = Exception("Stop failed")

            # Should not raise
            middleware.before_worker_shutdown(broker, worker)


class TestSerialise:
    """Test _serialise helper function."""

    def test_none_returns_none(self):
        """_serialise(None) should return None."""
        assert _serialise(None) is None

    def test_serialisable_returns_json(self):
        """_serialise should return JSON string for serialisable objects."""
        result = _serialise({"key": "value", "num": 42})
        assert result == '{"key": "value", "num": 42}'

    def test_list_returns_json(self):
        """_serialise should handle lists."""
        result = _serialise([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_non_serialisable_returns_repr(self):
        """_serialise should fall back to repr for non-serialisable objects."""

        class CustomObject:
            def __repr__(self):
                return "<CustomObject>"

        result = _serialise(CustomObject())
        assert result == "<CustomObject>"

    def test_circular_reference_returns_repr(self):
        """_serialise should handle circular references."""
        obj = {"key": None}
        obj["key"] = obj  # Circular reference

        result = _serialise(obj)
        assert "<dict" in result or "..." in result  # repr output


# ── _get_flush_threshold exception fallback (lines 115-116) ────────────────


class TestGetFlushThreshold:
    def test_returns_20_when_settings_raises(self):
        """_get_flush_threshold returns 20 when settings raises on access (lines 115-116)."""

        class _BadSettings:
            """Raises RuntimeError when any attribute is accessed."""

            @property
            def TASKS(self):
                raise RuntimeError("settings unavailable")

        with patch.object(_conf_module, "settings", new=_BadSettings()):
            result = _get_flush_threshold()

        assert result == 20

    def test_returns_configured_value(self):
        """_get_flush_threshold returns TASKS tracking_flush_threshold when set."""

        with patch.object(_conf_module, "settings") as ms:
            ms.TASKS = {"tracking_flush_threshold": 50}
            result = _get_flush_threshold()

        assert result == 50
