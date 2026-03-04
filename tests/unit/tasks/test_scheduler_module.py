"""Tests for openviper/tasks/scheduler.py — periodic, start_scheduler, stop_scheduler, etc."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.scheduler as sched_module
from openviper.tasks.schedule import CronSchedule, IntervalSchedule
from openviper.tasks.scheduler import (
    _enqueue,
    _tick_loop,
    periodic,
    reset_scheduler,
    start_scheduler,
    stop_scheduler,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_scheduler():
    """Guarantee a clean slate before and after every test."""
    reset_scheduler()
    yield
    reset_scheduler()


def _mock_actor(name: str = "my_actor") -> MagicMock:
    """Return a mock that looks like a Dramatiq actor."""
    actor = MagicMock()
    actor.actor_name = name
    return actor


# ---------------------------------------------------------------------------
# periodic — validation
# ---------------------------------------------------------------------------


def test_periodic_raises_when_neither_every_nor_cron():
    """Lines 99-102: both every and cron omitted → ValueError."""
    with pytest.raises(ValueError, match="requires 'every'"):
        periodic()


# ---------------------------------------------------------------------------
# periodic — decorator applied to an actor (lines 104-133)
# ---------------------------------------------------------------------------


def test_periodic_with_every_appends_to_pending():
    """Lines 104-133: applying @periodic(every=60) registers entry in _pending."""
    actor = _mock_actor("my_task")
    decorator = periodic(every=60)
    result = decorator(actor)

    assert result is actor  # actor returned unchanged
    assert len(sched_module._pending) == 1
    entry = sched_module._pending[0]
    assert entry["name"] == "my_task"
    assert isinstance(entry["schedule"], IntervalSchedule)
    assert entry["schedule"].seconds == 60
    assert entry["run_on_start"] is False
    assert entry["args"] == ()
    assert entry["kwargs"] == {}


def test_periodic_with_cron_creates_cron_schedule():
    """CronSchedule is created when 'cron' kwarg is supplied."""
    actor = _mock_actor("cron_task")
    decorator = periodic(cron="0 * * * *")
    decorator(actor)

    entry = sched_module._pending[0]
    assert isinstance(entry["schedule"], CronSchedule)
    assert entry["schedule"].expr == "0 * * * *"


def test_periodic_custom_name_overrides_actor_name():
    """'name=' kwarg overrides the actor_name for the registry entry."""
    actor = _mock_actor("original_name")
    periodic(every=30, name="custom_name")(actor)

    assert sched_module._pending[0]["name"] == "custom_name"


def test_periodic_run_on_start_stored_in_entry():
    """run_on_start=True is stored in the pending entry."""
    actor = _mock_actor()
    periodic(every=10, run_on_start=True)(actor)

    assert sched_module._pending[0]["run_on_start"] is True


def test_periodic_args_and_kwargs_stored():
    """Custom args/kwargs are forwarded to the pending entry."""
    actor = _mock_actor()
    periodic(every=60, args=(1, 2), kwargs={"dry_run": True})(actor)

    entry = sched_module._pending[0]
    assert entry["args"] == (1, 2)
    assert entry["kwargs"] == {"dry_run": True}


def test_periodic_kwargs_defaults_to_empty_dict_when_none():
    """kwargs=None is stored as {} so send(**{}) works without error."""
    actor = _mock_actor()
    periodic(every=60)(actor)  # no kwargs argument

    assert sched_module._pending[0]["kwargs"] == {}


def test_periodic_auto_wraps_plain_function():
    """Lines 107-109: plain function without actor_name is auto-wrapped with @task()."""

    def plain_func():
        pass

    mock_wrapped_actor = MagicMock()
    mock_wrapped_actor.actor_name = "plain_func"
    mock_task_decorator = MagicMock(return_value=mock_wrapped_actor)

    with patch("openviper.tasks.scheduler._pending", sched_module._pending):
        with patch("openviper.tasks.decorators.task", return_value=lambda fn: mock_wrapped_actor):
            result = periodic(every=60)(plain_func)

    # The result is the wrapped actor, not the plain function
    assert hasattr(result, "actor_name")


# ---------------------------------------------------------------------------
# start_scheduler — empty pending (lines 151-152)
# ---------------------------------------------------------------------------


def test_start_scheduler_noop_when_pending_empty():
    """Lines 151-152: _pending is empty → returns immediately, no thread started."""
    assert sched_module._pending == []
    start_scheduler()
    assert sched_module._tick_thread is None


# ---------------------------------------------------------------------------
# start_scheduler — thread already running (lines 154-156)
# ---------------------------------------------------------------------------


def test_start_scheduler_noop_when_thread_already_alive():
    """Lines 154-156: if tick thread is alive, start_scheduler returns early."""
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True

    actor = _mock_actor()
    sched_module._pending.append(
        {
            "name": "t",
            "actor": actor,
            "schedule": IntervalSchedule(60),
            "run_on_start": False,
            "args": (),
            "kwargs": {},
        }
    )
    sched_module._tick_thread = mock_thread

    start_scheduler()

    # Thread's start() was never called — we skipped the whole setup
    mock_thread.start.assert_not_called()


# ---------------------------------------------------------------------------
# start_scheduler — normal startup (lines 158-180)
# ---------------------------------------------------------------------------


def test_start_scheduler_starts_tick_thread():
    """Lines 158-177: start_scheduler() creates a Scheduler and starts tick thread."""
    actor = _mock_actor("interval_task")
    sched_module._pending.append(
        {
            "name": "interval_task",
            "actor": actor,
            "schedule": IntervalSchedule(3600),
            "run_on_start": False,
            "args": (),
            "kwargs": {},
        }
    )

    start_scheduler()

    assert sched_module._scheduler is not None
    assert sched_module._tick_thread is not None
    assert sched_module._tick_thread.is_alive()


def test_start_scheduler_enqueues_run_on_start_entry():
    """Lines 168-169: entries with run_on_start=True are enqueued immediately."""
    actor = _mock_actor("eager_task")
    sched_module._pending.append(
        {
            "name": "eager_task",
            "actor": actor,
            "schedule": IntervalSchedule(60),
            "run_on_start": True,
            "args": (1,),
            "kwargs": {"flag": True},
        }
    )

    start_scheduler()

    # actor.send(1, flag=True) must have been called once immediately
    actor.send.assert_called_once_with(1, flag=True)


def test_start_scheduler_logs_plural_tasks():
    """Line 179-180: 'tasks' (plural) used when more than one entry."""
    actor1 = _mock_actor("t1")
    actor2 = _mock_actor("t2")
    for actor in (actor1, actor2):
        sched_module._pending.append(
            {
                "name": actor.actor_name,
                "actor": actor,
                "schedule": IntervalSchedule(60),
                "run_on_start": False,
                "args": (),
                "kwargs": {},
            }
        )

    with patch("openviper.tasks.scheduler.logger") as mock_log:
        start_scheduler()

    # Should log "2 tasks registered"
    log_msg = str(mock_log.info.call_args_list)
    assert "2" in log_msg


# ---------------------------------------------------------------------------
# stop_scheduler (lines 190-197)
# ---------------------------------------------------------------------------


def test_stop_scheduler_sets_stop_event():
    """Line 190: _stop_event is set."""
    assert not sched_module._stop_event.is_set()
    stop_scheduler()
    assert sched_module._stop_event.is_set()


def test_stop_scheduler_joins_running_thread():
    """Lines 192-194: if tick thread is running, it is joined and cleared."""
    actor = _mock_actor()
    sched_module._pending.append(
        {
            "name": "t",
            "actor": actor,
            "schedule": IntervalSchedule(3600),
            "run_on_start": False,
            "args": (),
            "kwargs": {},
        }
    )
    start_scheduler()
    assert sched_module._tick_thread is not None

    stop_scheduler()

    assert sched_module._tick_thread is None
    assert sched_module._scheduler is None


def test_stop_scheduler_noop_when_no_thread():
    """stop_scheduler() is safe to call when no thread is running."""
    assert sched_module._tick_thread is None
    stop_scheduler()  # must not raise


# ---------------------------------------------------------------------------
# reset_scheduler (lines 206-208)
# ---------------------------------------------------------------------------


def test_reset_scheduler_clears_pending():
    """Lines 206-208: pending list is cleared."""
    actor = _mock_actor()
    sched_module._pending.append(
        {
            "name": "t",
            "actor": actor,
            "schedule": IntervalSchedule(60),
            "run_on_start": False,
            "args": (),
            "kwargs": {},
        }
    )
    assert len(sched_module._pending) == 1

    reset_scheduler()

    assert sched_module._pending == []


def test_reset_scheduler_stops_running_thread():
    """reset_scheduler() also stops any running tick thread."""
    actor = _mock_actor()
    sched_module._pending.append(
        {
            "name": "t",
            "actor": actor,
            "schedule": IntervalSchedule(3600),
            "run_on_start": False,
            "args": (),
            "kwargs": {},
        }
    )
    start_scheduler()
    assert sched_module._tick_thread is not None

    reset_scheduler()

    assert sched_module._tick_thread is None
    assert sched_module._pending == []


# ---------------------------------------------------------------------------
# _tick_loop (lines 218-226)
# ---------------------------------------------------------------------------


def _run_tick_loop_once(mock_scheduler):
    """Run _tick_loop in the current thread for exactly one iteration."""
    call_count = [0]

    original_wait = sched_module._stop_event.wait

    def mock_wait(timeout):
        call_count[0] += 1
        return call_count[0] > 1  # False (run) then True (stop)

    with patch.object(sched_module, "_scheduler", mock_scheduler):
        with patch.object(sched_module._stop_event, "wait", side_effect=mock_wait):
            _tick_loop()


def test_tick_loop_calls_scheduler_tick():
    """Lines 221-224: _tick_loop calls scheduler.tick() and logs fired tasks."""
    mock_sched = MagicMock()
    mock_sched.tick.return_value = ["task_a"]

    _run_tick_loop_once(mock_sched)

    mock_sched.tick.assert_called_once()


def test_tick_loop_logs_each_fired_task():
    """Line 224: logger.debug fired for each entry name."""
    mock_sched = MagicMock()
    mock_sched.tick.return_value = ["alpha", "beta"]

    with patch("openviper.tasks.scheduler.logger") as mock_log:
        _run_tick_loop_once(mock_sched)

    calls = [str(c) for c in mock_log.debug.call_args_list]
    assert any("alpha" in c for c in calls)
    assert any("beta" in c for c in calls)


def test_tick_loop_logs_warning_on_exception():
    """Lines 225-226: exception from tick() logs a warning and does not propagate."""
    mock_sched = MagicMock()
    mock_sched.tick.side_effect = RuntimeError("tick boom")

    with patch("openviper.tasks.scheduler.logger") as mock_log:
        _run_tick_loop_once(mock_sched)  # must not raise

    mock_log.warning.assert_called()
    assert "tick boom" in str(mock_log.warning.call_args)


def test_tick_loop_exits_when_scheduler_is_none():
    """Lines 219-220: loop body breaks immediately if _scheduler becomes None."""
    call_count = [0]

    def mock_wait(timeout):
        call_count[0] += 1
        return False  # never stop via event — exits via `_scheduler is None` break

    with patch.object(sched_module, "_scheduler", None):
        with patch.object(sched_module._stop_event, "wait", side_effect=mock_wait):
            _tick_loop()

    assert call_count[0] == 1  # ran once, then broke out


# ---------------------------------------------------------------------------
# _enqueue (lines 236-240)
# ---------------------------------------------------------------------------


def test_enqueue_calls_actor_send():
    """Lines 236-239: actor.send(*args, **kwargs) is called."""
    actor = MagicMock()
    _enqueue(actor, "my_task", (1, 2), {"key": "value"})
    actor.send.assert_called_once_with(1, 2, key="value")


def test_enqueue_logs_warning_on_exception():
    """Line 240: exception from actor.send() logs a warning and does not propagate."""
    actor = MagicMock()
    actor.send.side_effect = RuntimeError("broker down")

    with patch("openviper.tasks.scheduler.logger") as mock_log:
        _enqueue(actor, "broken_task", (), {})  # must not raise

    mock_log.warning.assert_called()
    assert "broken_task" in str(mock_log.warning.call_args)
