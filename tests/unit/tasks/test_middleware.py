"""Unit tests for openviper.tasks.middleware — batched task tracking.

Covers:
- ``_TrackingEvent`` slots dataclass
- ``_EventBuffer`` threshold flush / terminal flush / exception suppression
- ``TaskTrackingMiddleware`` lifecycle hooks: before_enqueue,
  before_process_message, after_process_message (success + failure),
  after_skip_message, after_nack
- Integration: full lifecycle triggers exactly one batch_upsert_results call
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.middleware import (
    TaskTrackingMiddleware,
    _event_buffer,
    _EventBuffer,
    _serialise,
    _TrackingEvent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    message_id: str = "test-msg-id",
    actor_name: str = "test.actor",
    queue_name: str = "default",
) -> MagicMock:
    msg = MagicMock()
    msg.message_id = message_id
    msg.actor_name = actor_name
    msg.queue_name = queue_name
    msg.args = [1, 2]
    msg.kwargs = {"key": "value"}
    return msg


@pytest.fixture(autouse=True)
def reset_global_buffer():
    """Clear the module-level event buffer before and after each test."""
    _event_buffer._queue.clear()
    yield
    _event_buffer._queue.clear()


# ---------------------------------------------------------------------------
# _TrackingEvent
# ---------------------------------------------------------------------------


def test_tracking_event_has_slots():
    """_TrackingEvent must use __slots__ (no __dict__)."""
    event = _TrackingEvent(
        message_id="id-1",
        fields={"status": "pending"},
        terminal=False,
    )
    assert not hasattr(event, "__dict__"), "_TrackingEvent should use __slots__"


def test_tracking_event_stores_fields():
    event = _TrackingEvent(
        message_id="abc",
        fields={"status": "running"},
        terminal=True,
    )
    assert event.message_id == "abc"
    assert event.fields["status"] == "running"
    assert event.terminal is True


# ---------------------------------------------------------------------------
# _EventBuffer — threshold flush
# ---------------------------------------------------------------------------


def test_event_buffer_no_flush_below_threshold():
    buf = _EventBuffer(flush_threshold=5)
    with patch("openviper.tasks.middleware.batch_upsert_results") as mock_upsert:
        # Push 4 / 5 non-terminal events — should not flush yet.
        for i in range(4):
            buf.push(_TrackingEvent(f"id-{i}", {"status": "pending"}, terminal=False))
    mock_upsert.assert_not_called()


def test_event_buffer_flushes_at_threshold():
    buf = _EventBuffer(flush_threshold=3)
    captured: list[list] = []

    def fake_batch(events):
        captured.append(list(events))

    with patch("openviper.tasks.middleware.batch_upsert_results", side_effect=fake_batch):
        for i in range(3):
            buf.push(_TrackingEvent(f"id-{i}", {"status": "pending"}, terminal=False))

    assert len(captured) == 1
    assert len(captured[0]) == 3


def test_event_buffer_flushes_on_terminal_below_threshold():
    buf = _EventBuffer(flush_threshold=20)
    captured: list = []

    with patch(
        "openviper.tasks.middleware.batch_upsert_results", side_effect=lambda e: captured.extend(e)
    ):
        buf.push(_TrackingEvent("before", {"status": "running"}, terminal=False))
        buf.push(_TrackingEvent("terminal", {"status": "success"}, terminal=True))

    # The terminal event triggered an immediate flush of both events.
    assert len(captured) == 2
    assert captured[1][0] == "terminal"


def test_event_buffer_queue_is_empty_after_flush():
    buf = _EventBuffer(flush_threshold=2)
    with patch("openviper.tasks.middleware.batch_upsert_results"):
        buf.push(_TrackingEvent("a", {}, terminal=False))
        buf.push(_TrackingEvent("b", {}, terminal=False))  # triggers flush
    assert len(buf._queue) == 0


def test_event_buffer_flush_exception_is_suppressed():
    """A failing batch_upsert_results must not propagate out of push()."""
    buf = _EventBuffer(flush_threshold=1)
    with patch(
        "openviper.tasks.middleware.batch_upsert_results",
        side_effect=RuntimeError("DB down"),
    ):
        # Must not raise:
        buf.push(_TrackingEvent("x", {"status": "pending"}, terminal=False))


def test_event_buffer_passes_correct_tuple_format():
    """_flush must call batch_upsert_results with (message_id, fields) tuples."""
    buf = _EventBuffer(flush_threshold=1)
    captured: list = []

    with patch(
        "openviper.tasks.middleware.batch_upsert_results",
        side_effect=lambda events: captured.extend(events),
    ):
        buf.push(_TrackingEvent("msg-001", {"status": "pending", "foo": "bar"}, terminal=False))

    assert len(captured) == 1
    message_id, fields = captured[0]
    assert message_id == "msg-001"
    assert fields["status"] == "pending"
    assert fields["foo"] == "bar"


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — before_enqueue
# ---------------------------------------------------------------------------


def test_before_enqueue_pushes_pending_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="enqueue-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.before_enqueue(MagicMock(), msg, None)

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "enqueue-id"
    assert event.fields["status"] == "pending"
    assert event.fields["actor_name"] == "test.actor"
    assert event.terminal is False


def test_before_enqueue_exception_is_silent():
    mw = TaskTrackingMiddleware()
    with patch.object(_event_buffer, "push", side_effect=RuntimeError("oops")):
        # Must not raise:
        mw.before_enqueue(MagicMock(), _make_message(), None)


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — before_process_message
# ---------------------------------------------------------------------------


def test_before_process_message_pushes_running_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="run-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.before_process_message(MagicMock(), msg)

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "run-id"
    assert event.fields["status"] == "running"
    assert event.terminal is False


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — after_process_message (success)
# ---------------------------------------------------------------------------


def test_after_process_message_success_pushes_success_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="ok-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.after_process_message(MagicMock(), msg, result="my-result", exception=None)

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "ok-id"
    assert event.fields["status"] == "success"
    assert event.terminal is True


def test_after_process_message_success_serialises_result():
    mw = TaskTrackingMiddleware()
    msg = _make_message()
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.after_process_message(MagicMock(), msg, result={"key": 42}, exception=None)

    result_field = pushed[0].fields.get("result")
    assert result_field == '{"key": 42}'


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — after_process_message (failure)
# ---------------------------------------------------------------------------


def test_after_process_message_failure_pushes_failure_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="fail-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.after_process_message(MagicMock(), msg, result=None, exception=ValueError("boom"))

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "fail-id"
    assert event.fields["status"] == "failure"
    assert "boom" in event.fields["error"]
    assert event.terminal is True


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — after_skip_message
# ---------------------------------------------------------------------------


def test_after_skip_message_pushes_skipped_terminal_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="skip-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.after_skip_message(MagicMock(), msg)

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "skip-id"
    assert event.fields["status"] == "skipped"
    assert event.terminal is True


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware — after_nack
# ---------------------------------------------------------------------------


def test_after_nack_pushes_dead_terminal_event():
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="nack-id")
    pushed: list[_TrackingEvent] = []

    with patch.object(_event_buffer, "push", side_effect=pushed.append):
        mw.after_nack(MagicMock(), msg)

    assert len(pushed) == 1
    event = pushed[0]
    assert event.message_id == "nack-id"
    assert event.fields["status"] == "dead"
    assert event.terminal is True


# ---------------------------------------------------------------------------
# _serialise helper
# ---------------------------------------------------------------------------


def test_serialise_none_returns_none():
    assert _serialise(None) is None


def test_serialise_dict():
    assert _serialise({"a": 1}) == '{"a": 1}'


def test_serialise_unserializable_returns_repr():
    result = _serialise(lambda x: x)
    assert result is not None
    assert "function" in result or "lambda" in result


# ---------------------------------------------------------------------------
# Integration: full lifecycle → batch_upsert_results called once at terminal
# ---------------------------------------------------------------------------


def test_full_lifecycle_flushes_on_success():
    """pending→running→success lifecycle triggers exactly one batch flush."""
    buf = _EventBuffer(flush_threshold=20)  # high threshold; only terminal triggers flush
    mw = TaskTrackingMiddleware()
    msg = _make_message(message_id="lifecycle-id")
    broker = MagicMock()
    flushed: list[list] = []

    with (
        patch("openviper.tasks.middleware._event_buffer", buf),
        patch(
            "openviper.tasks.middleware.batch_upsert_results",
            side_effect=lambda events: flushed.append(list(events)),
        ),
    ):
        mw.before_enqueue(broker, msg, None)  # pending  — non-terminal
        mw.before_process_message(broker, msg)  # running  — non-terminal
        mw.after_process_message(  # success  — terminal → FLUSH
            broker, msg, result="done", exception=None
        )

    # Exactly one flush triggered by the terminal event.
    assert len(flushed) == 1
    message_ids = [ev[0] for ev in flushed[0]]
    assert all(mid == "lifecycle-id" for mid in message_ids)
    statuses = [ev[1]["status"] for ev in flushed[0]]
    assert statuses == ["pending", "running", "success"]


# ---------------------------------------------------------------------------
# reset_tracking_buffer 
# ---------------------------------------------------------------------------


def test_reset_tracking_buffer_clears_queue():
    from openviper.tasks.middleware import reset_tracking_buffer

    # Pre-populate buffer
    _event_buffer._queue.append(_TrackingEvent("id-x", {"status": "pending"}, terminal=False))
    assert len(_event_buffer._queue) > 0
    reset_tracking_buffer()
    assert len(_event_buffer._queue) == 0


# ---------------------------------------------------------------------------
# TaskTrackingMiddleware exception handler paths
# ---------------------------------------------------------------------------


def _make_bad_message():
    """Message whose attribute access raises to exercise exception handlers."""
    msg = MagicMock()
    msg.message_id = "bad-id"
    msg.actor_name = "bad_actor"
    msg.queue_name = "default"
    # args and kwargs raise to trigger the except block
    type(msg).args = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    return msg


def test_before_process_message_exception_is_swallowed():
    mw = TaskTrackingMiddleware()
    broker = MagicMock()

    # Make the push fail by having message_id raise
    bad_msg = MagicMock()
    type(bad_msg).message_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))

    # Must not raise
    mw.before_process_message(broker, bad_msg)


def test_after_process_message_exception_is_swallowed():
    mw = TaskTrackingMiddleware()
    broker = MagicMock()

    bad_msg = MagicMock()
    type(bad_msg).message_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))

    # Must not raise in either success or failure path
    mw.after_process_message(broker, bad_msg, result="ok", exception=None)
    mw.after_process_message(broker, bad_msg, result=None, exception=ValueError("fail"))


def test_after_skip_message_exception_is_swallowed():
    mw = TaskTrackingMiddleware()
    broker = MagicMock()

    bad_msg = MagicMock()
    type(bad_msg).message_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))

    mw.after_skip_message(broker, bad_msg)


def test_after_nack_exception_is_swallowed():
    mw = TaskTrackingMiddleware()
    broker = MagicMock()

    bad_msg = MagicMock()
    type(bad_msg).message_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))

    mw.after_nack(broker, bad_msg)


# ---------------------------------------------------------------------------
# SchedulerMiddleware — after_worker_boot and before_worker_shutdown
# ---------------------------------------------------------------------------


def test_scheduler_middleware_after_worker_boot_success():
    from openviper.tasks.middleware import SchedulerMiddleware

    mw = SchedulerMiddleware()
    broker = MagicMock()
    worker = MagicMock()

    with patch("openviper.tasks.scheduler.start_scheduler") as mock_start:
        mw.after_worker_boot(broker, worker)
    mock_start.assert_called_once()


def test_scheduler_middleware_after_worker_boot_exception_is_logged():
    from openviper.tasks.middleware import SchedulerMiddleware

    mw = SchedulerMiddleware()
    broker = MagicMock()
    worker = MagicMock()

    with patch(
        "openviper.tasks.scheduler.start_scheduler",
        side_effect=RuntimeError("start failed"),
    ):
        mw.after_worker_boot(broker, worker)  # must not raise


def test_scheduler_middleware_before_worker_shutdown_success():
    from openviper.tasks.middleware import SchedulerMiddleware

    mw = SchedulerMiddleware()
    broker = MagicMock()
    worker = MagicMock()

    with patch("openviper.tasks.scheduler.stop_scheduler") as mock_stop:
        mw.before_worker_shutdown(broker, worker)
    mock_stop.assert_called_once()


def test_scheduler_middleware_before_worker_shutdown_exception_is_logged():
    from openviper.tasks.middleware import SchedulerMiddleware

    mw = SchedulerMiddleware()
    broker = MagicMock()
    worker = MagicMock()

    with patch(
        "openviper.tasks.scheduler.stop_scheduler",
        side_effect=RuntimeError("stop failed"),
    ):
        mw.before_worker_shutdown(broker, worker)  # must not raise
