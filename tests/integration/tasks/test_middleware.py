"""Integration tests for task tracking and scheduler middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from dramatiq import Message

from openviper.tasks.middleware import (
    SchedulerMiddleware,
    TaskTrackingMiddleware,
    _TrackingEvent,
    reset_tracking_buffer,
)


@pytest.fixture(autouse=True)
def clean_buffer():
    """Ensure the tracking buffer is reset before and after each test."""
    reset_tracking_buffer()
    yield
    reset_tracking_buffer()


def test_event_buffer_batching():
    """Test that events are buffered and flushed at threshold."""
    from openviper.tasks.middleware import _EventBuffer

    # Mock batch_upsert_results to track flushes
    with patch("openviper.tasks.middleware.batch_upsert_results") as mock_flush:
        buffer = _EventBuffer(flush_threshold=3)

        # 1. First event (non-terminal)
        buffer.push(_TrackingEvent(message_id="m1", fields={"s": 1}, terminal=False))
        mock_flush.assert_not_called()

        # 2. Second event (non-terminal)
        buffer.push(_TrackingEvent(message_id="m2", fields={"s": 2}, terminal=False))
        mock_flush.assert_not_called()

        # 3. Third event (threshold reached)
        buffer.push(_TrackingEvent(message_id="m3", fields={"s": 3}, terminal=False))
        mock_flush.assert_called_once()
        assert len(mock_flush.call_args[0][0]) == 3


def test_event_buffer_terminal_flush():
    """Test that terminal events trigger immediate flush."""
    from openviper.tasks.middleware import _EventBuffer

    with patch("openviper.tasks.middleware.batch_upsert_results") as mock_flush:
        buffer = _EventBuffer(flush_threshold=10)

        # Push non-terminal
        buffer.push(_TrackingEvent(message_id="m1", fields={"s": 1}, terminal=False))
        mock_flush.assert_not_called()

        # Push terminal
        buffer.push(_TrackingEvent(message_id="m2", fields={"s": 2}, terminal=True))
        mock_flush.assert_called_once()
        assert len(mock_flush.call_args[0][0]) == 2


def test_task_tracking_middleware_hooks():
    """Verify middleware hooks push correct events to buffer."""
    mw = TaskTrackingMiddleware()
    broker = MagicMock()
    message = Message(
        queue_name="default",
        actor_name="test_actor",
        args=(1,),
        kwargs={"a": 2},
        options={},
    )

    with patch("openviper.tasks.middleware._event_buffer.push") as mock_push:
        # before_enqueue
        mw.before_enqueue(broker, message, delay=None)
        mock_push.assert_called()
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "pending"
        assert event.terminal is False

        # before_process_message
        mw.before_process_message(broker, message)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "running"

        # after_process_message (success)
        mw.after_process_message(broker, message, result="OK")
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "success"
        assert event.terminal is True

        # after_process_message (failure)
        mw.after_process_message(broker, message, exception=ValueError("fail"))
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "failure"
        assert event.terminal is True

        # after_skip_message
        mw.after_skip_message(broker, message)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "skipped"

        # after_nack
        mw.after_nack(broker, message)
        event = mock_push.call_args[0][0]
        assert event.fields["status"] == "dead"


def test_scheduler_middleware_hooks():
    """Verify scheduler middleware calls start/stop scheduler."""
    mw = SchedulerMiddleware()
    broker = MagicMock()
    worker = MagicMock()

    with patch("openviper.tasks.scheduler.start_scheduler") as mock_start:
        mw.after_worker_boot(broker, worker)
        mock_start.assert_called_once()

    with patch("openviper.tasks.scheduler.stop_scheduler") as mock_stop:
        mw.before_worker_shutdown(broker, worker)
        mock_stop.assert_called_once()


def test_middleware_error_suppression():
    """Ensure middleware hooks don't raise exceptions if internal calls fail."""
    mw = TaskTrackingMiddleware()
    broker = MagicMock()
    message = MagicMock()  # Will trigger attribute error on message.message_id

    # Should not raise
    mw.before_enqueue(broker, message, delay=None)
    mw.before_process_message(broker, message)
    mw.after_process_message(broker, message)
