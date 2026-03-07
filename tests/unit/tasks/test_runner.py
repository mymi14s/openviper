"""Tests for openviper/tasks/runner.py (run_scheduler entry-point)."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(tick_return=None):
    """Return a mock Scheduler whose tick() returns *tick_return*."""
    scheduler = MagicMock()
    scheduler.__len__ = MagicMock(return_value=2)
    scheduler.tick.return_value = tick_return or []
    return scheduler


# ---------------------------------------------------------------------------
# run_scheduler — basic loop
# ---------------------------------------------------------------------------


def test_run_scheduler_explicit_scheduler_keyboard_interrupt():
    """Loop exits cleanly on KeyboardInterrupt; sys.exit(0) is called."""
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler()

    with (
        patch("openviper.tasks.runner.time.sleep", side_effect=KeyboardInterrupt),
        patch("openviper.tasks.runner.sys.exit") as mock_exit,
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.001)

    mock_exit.assert_called_once_with(0)
    scheduler.tick.assert_called()


def test_run_scheduler_explicit_scheduler_system_exit():
    """Loop exits cleanly on SystemExit; sys.exit(0) is called."""
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler()

    with (
        patch("openviper.tasks.runner.time.sleep", side_effect=SystemExit),
        patch("openviper.tasks.runner.sys.exit") as mock_exit,
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.001)

    mock_exit.assert_called_once_with(0)


def test_run_scheduler_creates_default_scheduler_when_none_provided():
    from openviper.tasks.runner import run_scheduler

    mock_sched = _make_scheduler()

    with (
        patch("openviper.tasks.runner.Scheduler", return_value=mock_sched) as mock_cls,
        patch("openviper.tasks.runner.time.sleep", side_effect=KeyboardInterrupt),
        patch("openviper.tasks.runner.sys.exit"),
    ):
        run_scheduler()  # no scheduler= argument

    mock_cls.assert_called_once_with()
    mock_sched.tick.assert_called()


def test_run_scheduler_logs_enqueued_tasks():
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler(tick_return=["task_a", "task_b"])

    with (
        patch("openviper.tasks.runner.time.sleep", side_effect=KeyboardInterrupt),
        patch("openviper.tasks.runner.sys.exit"),
        patch("openviper.tasks.runner.logger") as mock_logger,
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.001)

    # logger.debug called with the enqueued list
    mock_logger.debug.assert_any_call("Tick enqueued: %s", ["task_a", "task_b"])


def test_run_scheduler_empty_tick_does_not_log_debug():
    """When tick() returns [], the debug log for 'Tick enqueued' is NOT called."""
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler(tick_return=[])

    with (
        patch("openviper.tasks.runner.time.sleep", side_effect=KeyboardInterrupt),
        patch("openviper.tasks.runner.sys.exit"),
        patch("openviper.tasks.runner.logger") as mock_logger,
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.001)

    for c in mock_logger.debug.call_args_list:
        assert "Tick enqueued" not in str(c)


# ---------------------------------------------------------------------------
# run_scheduler — signal handler
# ---------------------------------------------------------------------------


def test_run_scheduler_sigint_handler_sets_running_false():
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler()
    captured: dict = {}

    def capture_signal(signum, handler):
        captured[signum] = handler

    sleep_calls = [0]

    def sleep_side_effect(t):
        sleep_calls[0] += 1
        if sleep_calls[0] == 1:
            # Invoke the SIGINT handler → sets _running=False
            captured[signal.SIGINT](signal.SIGINT, None)
        # Return normally; loop condition checked next → exits

    with (
        patch("openviper.tasks.runner.signal.signal", side_effect=capture_signal),
        patch("openviper.tasks.runner.time.sleep", side_effect=sleep_side_effect),
        patch("openviper.tasks.runner.sys.exit") as mock_exit,
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.001)

    mock_exit.assert_called_once_with(0)
    # Loop ran exactly once (one tick + one sleep)
    assert sleep_calls[0] == 1


def test_run_scheduler_sigterm_handler_registered():
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler()
    registered_sigs: list = []

    def capture_signal(signum, handler):
        registered_sigs.append(signum)

    with (
        patch("openviper.tasks.runner.signal.signal", side_effect=capture_signal),
        patch("openviper.tasks.runner.time.sleep", side_effect=KeyboardInterrupt),
        patch("openviper.tasks.runner.sys.exit"),
    ):
        run_scheduler(scheduler=scheduler)

    assert signal.SIGINT in registered_sigs
    assert signal.SIGTERM in registered_sigs


def test_run_scheduler_custom_tick_interval():
    """The tick_interval argument is passed to time.sleep."""
    from openviper.tasks.runner import run_scheduler

    scheduler = _make_scheduler()
    sleep_args: list = []

    def capture_sleep(t):
        sleep_args.append(t)
        raise KeyboardInterrupt

    with (
        patch("openviper.tasks.runner.time.sleep", side_effect=capture_sleep),
        patch("openviper.tasks.runner.sys.exit"),
    ):
        run_scheduler(scheduler=scheduler, tick_interval=0.123)

    assert sleep_args == [0.123]
