"""Unit tests for openviper.tasks.scheduler — Periodic task scheduler."""

from unittest.mock import MagicMock, patch

import pytest

import openviper.tasks.scheduler as _sched_mod
from openviper.tasks import scheduler
from openviper.tasks.schedule import CronSchedule, IntervalSchedule
from openviper.tasks.scheduler import (
    _enqueue,
    _pending,
    _tick_loop,
    periodic,
    reset_scheduler,
    start_scheduler,
    stop_scheduler,
)


class TestPeriodicDecorator:
    """Test @periodic decorator."""

    @pytest.fixture(autouse=True)
    def mock_task_registration(self):
        """Mock task/broker registration to prevent Dramatiq actor name collisions."""
        _pending.clear()
        with (
            patch("openviper.tasks.decorators.get_broker"),
            patch("openviper.tasks.decorators.dramatiq.actor") as mock_actor,
        ):

            def fake_actor(fn, **kwargs):
                mock = MagicMock()
                mock.actor_name = kwargs.get("actor_name", fn.__name__)
                mock.send = MagicMock()
                return mock

            mock_actor.side_effect = fake_actor
            yield
        _pending.clear()

    def test_requires_every_or_cron(self):
        """Should raise ValueError if neither every nor cron is provided."""
        with pytest.raises(ValueError, match="requires 'every'.*or 'cron'"):

            @periodic()
            def my_task():
                pass

    def test_with_every_interval(self):
        """Should register task with IntervalSchedule."""
        _pending.clear()

        @periodic(every=60)
        def my_task():
            pass

        assert len(_pending) == 1
        entry = _pending[0]
        assert isinstance(entry["schedule"], IntervalSchedule)
        assert entry["schedule"].seconds == 60

    def test_with_cron_expression(self):
        """Should register task with CronSchedule."""
        _pending.clear()

        @periodic(cron="0 * * * *")
        def my_task():
            pass

        assert len(_pending) == 1
        entry = _pending[0]
        assert isinstance(entry["schedule"], CronSchedule)
        assert entry["schedule"].expr == "0 * * * *"

    def test_auto_wraps_plain_function(self):
        """Should auto-wrap plain function with @task."""
        _pending.clear()

        @periodic(every=60)
        def my_task():
            pass

        # Should have actor_name attribute after auto-wrapping
        assert hasattr(my_task, "actor_name")

    def test_does_not_wrap_existing_actor(self):
        """Should not double-wrap if function is already an actor."""
        _pending.clear()

        mock_actor = MagicMock()
        mock_actor.actor_name = "test_actor"

        @periodic(every=60)
        def decorator_test():
            return mock_actor

        result = decorator_test()

        # Should still have the actor
        assert hasattr(result, "actor_name")

    def test_custom_name(self):
        """Should use custom name when provided."""
        _pending.clear()

        @periodic(every=60, name="custom_name")
        def my_task():
            pass

        entry = _pending[0]
        assert entry["name"] == "custom_name"

    def test_default_name_from_actor(self):
        """Should default to actor_name when no name provided."""
        _pending.clear()

        @periodic(every=60)
        def my_custom_task():
            pass

        entry = _pending[0]
        assert entry["name"] == "my_custom_task"

    def test_with_args_and_kwargs(self):
        """Should store args and kwargs."""
        _pending.clear()

        @periodic(every=60, args=(1, 2), kwargs={"key": "value"})
        def my_task():
            pass

        entry = _pending[0]
        assert entry["args"] == (1, 2)
        assert entry["kwargs"] == {"key": "value"}

    def test_run_on_start_flag(self):
        """Should store run_on_start flag."""
        _pending.clear()

        @periodic(every=60, run_on_start=True)
        def my_task():
            pass

        entry = _pending[0]
        assert entry["run_on_start"] is True

    def test_multiple_registrations(self):
        """Should allow multiple @periodic registrations."""
        _pending.clear()

        @periodic(every=60)
        def task1():
            pass

        @periodic(every=120)
        def task2():
            pass

        assert len(_pending) == 2


class TestStartScheduler:
    """Test start_scheduler function."""

    def test_does_nothing_when_no_pending_tasks(self):
        """Should be no-op when _pending is empty."""
        reset_scheduler()

        with patch("openviper.tasks.scheduler.Scheduler") as mock_scheduler_class:
            start_scheduler()

            mock_scheduler_class.assert_not_called()

    def test_creates_scheduler_and_registers_tasks(self):
        """Should create Scheduler and register all pending tasks."""
        reset_scheduler()
        _pending.clear()

        mock_actor = MagicMock()
        mock_actor.actor_name = "test_actor"
        _pending.append(
            {
                "name": "test",
                "actor": mock_actor,
                "schedule": IntervalSchedule(60),
                "args": (),
                "kwargs": {},
                "run_on_start": False,
            }
        )

        with patch("openviper.tasks.scheduler.Scheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler

            with patch("openviper.tasks.scheduler.threading.Thread") as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                start_scheduler()

                mock_scheduler.add.assert_called_once()
                mock_thread_instance.start.assert_called_once()

    def test_enqueues_run_on_start_tasks(self):
        """Should immediately enqueue tasks with run_on_start=True."""
        reset_scheduler()
        _pending.clear()

        mock_actor = MagicMock()
        mock_actor.actor_name = "test_actor"
        _pending.append(
            {
                "name": "test",
                "actor": mock_actor,
                "schedule": IntervalSchedule(60),
                "args": (1, 2),
                "kwargs": {"key": "value"},
                "run_on_start": True,
            }
        )

        with patch("openviper.tasks.scheduler.Scheduler"):
            with patch("openviper.tasks.scheduler.threading.Thread"):
                with patch("openviper.tasks.scheduler._enqueue") as mock_enqueue:
                    start_scheduler()

                    mock_enqueue.assert_called_once_with(
                        mock_actor, "test", (1, 2), {"key": "value"}
                    )

    def test_starts_tick_thread(self):
        """Should start daemon tick thread."""
        reset_scheduler()
        _pending.clear()

        mock_actor = MagicMock()
        mock_actor.actor_name = "test_actor"
        _pending.append(
            {
                "name": "test",
                "actor": mock_actor,
                "schedule": IntervalSchedule(60),
                "args": (),
                "kwargs": {},
                "run_on_start": False,
            }
        )

        with patch("openviper.tasks.scheduler.Scheduler"):
            with patch("openviper.tasks.scheduler.threading.Thread") as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                start_scheduler()

                mock_thread.assert_called_once()
                call_kwargs = mock_thread.call_args[1]
                assert call_kwargs["daemon"] is True
                assert call_kwargs["name"] == "openviper.tasks.scheduler"

    def test_skips_if_already_running(self):
        """Should skip if tick thread is already running."""
        reset_scheduler()
        _pending.clear()

        mock_actor = MagicMock()
        mock_actor.actor_name = "test_actor"
        _pending.append(
            {
                "name": "test",
                "actor": mock_actor,
                "schedule": IntervalSchedule(60),
                "args": (),
                "kwargs": {},
                "run_on_start": False,
            }
        )

        with patch("openviper.tasks.scheduler.Scheduler"):
            with patch("openviper.tasks.scheduler.threading.Thread") as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread_instance.is_alive.return_value = True
                mock_thread.return_value = mock_thread_instance

                # Import _tick_thread after patches
                scheduler._tick_thread = mock_thread_instance

                start_scheduler()

                # Should not start a new thread
                mock_thread_instance.start.assert_not_called()


class TestStopScheduler:
    """Test stop_scheduler function."""

    def test_sets_stop_event(self):
        """Should set the _stop_event."""
        reset_scheduler()

        with patch("openviper.tasks.scheduler._stop_event") as mock_event:
            stop_scheduler()

            mock_event.set.assert_called_once()

    def test_joins_tick_thread(self):
        """Should join the tick thread."""
        reset_scheduler()

        mock_thread = MagicMock()

        with patch("openviper.tasks.scheduler._tick_thread", mock_thread):
            stop_scheduler()

            mock_thread.join.assert_called_once()

    def test_handles_no_thread(self):
        """Should handle case when no thread exists."""
        reset_scheduler()

        # Should not raise
        stop_scheduler()


class TestResetScheduler:
    """Test reset_scheduler function."""

    def test_stops_scheduler(self):
        """Should call stop_scheduler."""
        with patch("openviper.tasks.scheduler.stop_scheduler") as mock_stop:
            reset_scheduler()

            mock_stop.assert_called_once()

    def test_clears_pending_list(self):
        """Should clear _pending list."""
        _pending.clear()
        _pending.append({"name": "test"})

        reset_scheduler()

        assert len(_pending) == 0

    def test_clears_stop_event(self):
        """Should clear _stop_event."""
        with patch("openviper.tasks.scheduler._stop_event") as mock_event:
            reset_scheduler()

            mock_event.clear.assert_called()


class TestTickLoop:
    """Test _tick_loop internal function."""

    def test_ticks_scheduler_until_stopped(self):
        """Should call scheduler.tick() in a loop until stopped."""
        mock_scheduler = MagicMock()
        mock_scheduler.tick.return_value = []

        with patch("openviper.tasks.scheduler._scheduler", mock_scheduler):
            with patch("openviper.tasks.scheduler._stop_event") as mock_event:
                # Stop after first tick
                mock_event.wait.side_effect = [False, True]

                _tick_loop()

                assert mock_scheduler.tick.call_count >= 1

    def test_handles_tick_errors(self):
        """Should catch and log errors from scheduler.tick()."""
        mock_scheduler = MagicMock()
        mock_scheduler.tick.side_effect = Exception("Tick failed")

        with patch("openviper.tasks.scheduler._scheduler", mock_scheduler):
            with patch("openviper.tasks.scheduler._stop_event") as mock_event:
                mock_event.wait.side_effect = [False, True]

                with patch("openviper.tasks.scheduler.logger") as mock_logger:
                    _tick_loop()

                    # Should log the error
                    assert mock_logger.warning.called

    def test_waits_one_second_between_ticks(self):
        """Should wait 1 second between ticks."""
        mock_scheduler = MagicMock()
        mock_scheduler.tick.return_value = []

        with patch("openviper.tasks.scheduler._scheduler", mock_scheduler):
            with patch("openviper.tasks.scheduler._stop_event") as mock_event:
                mock_event.wait.side_effect = [False, True]

                _tick_loop()

                # wait() is called with timeout=1.0
                calls = mock_event.wait.call_args_list
                assert calls[0][0][0] == 1.0


class TestEnqueue:
    """Test _enqueue internal function."""

    def test_enqueues_task(self):
        """Should call actor.send() with args and kwargs."""
        mock_actor = MagicMock()

        _enqueue(mock_actor, "test_name", (1, 2), {"key": "value"})

        mock_actor.send.assert_called_once_with(1, 2, key="value")

    def test_handles_enqueue_error(self):
        """Should catch and log errors from actor.send()."""
        mock_actor = MagicMock()
        mock_actor.send.side_effect = Exception("Enqueue failed")

        with patch("openviper.tasks.scheduler.logger") as mock_logger:
            _enqueue(mock_actor, "test_name", (), {})

            # Should log the error
            assert mock_logger.warning.called


class TestTickLoopBranches:
    def test_tick_loop_breaks_when_scheduler_is_none(self):
        """_tick_loop breaks out of the while loop when _scheduler is None."""

        with patch.object(_sched_mod, "_scheduler", None):
            with patch.object(_sched_mod, "_stop_event") as mock_event:
                # wait() returns False → enter loop body; _scheduler is None → break
                mock_event.wait.side_effect = [False]
                _tick_loop()  # must not raise or loop forever
                mock_event.wait.assert_called_once()

    def test_tick_loop_logs_fired_entries(self):
        """_tick_loop logs each fired task name when tick() returns non-empty."""

        mock_scheduler = MagicMock()
        mock_scheduler.tick.return_value = ["my_task", "other_task"]

        with patch.object(_sched_mod, "_scheduler", mock_scheduler):
            with patch.object(_sched_mod, "_stop_event") as mock_event:
                mock_event.wait.side_effect = [False, True]
                with patch.object(_sched_mod, "logger") as mock_logger:
                    _tick_loop()

        debug_calls = mock_logger.debug.call_args_list
        logged_names = [c[0][1] for c in debug_calls]
        assert "my_task" in logged_names
        assert "other_task" in logged_names
