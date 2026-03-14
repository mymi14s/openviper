"""Unit tests for openviper.tasks.core — Scheduler class."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.core import Scheduler
from openviper.tasks.registry import ScheduleRegistry, get_registry, reset_registry
from openviper.tasks.schedule import CronSchedule, IntervalSchedule


@pytest.fixture
def mock_actor():
    """Create a mock Dramatiq actor."""
    actor = MagicMock()
    actor.send = MagicMock()
    actor.actor_name = "test_actor"
    return actor


@pytest.fixture
def clean_registry():
    """Provide a clean registry for each test."""
    reset_registry()
    yield
    reset_registry()


class TestSchedulerInit:
    """Test Scheduler initialization."""

    def test_init_default_registry(self, clean_registry):
        """Scheduler should use process-level registry by default."""
        scheduler = Scheduler()
        assert scheduler._registry is get_registry()

    def test_init_custom_registry(self):
        """Scheduler should accept a custom registry."""
        custom_registry = ScheduleRegistry()
        scheduler = Scheduler(registry=custom_registry)
        assert scheduler._registry is custom_registry


class TestSchedulerAdd:
    """Test Scheduler.add method."""

    def test_add_with_interval(self, mock_actor, clean_registry):
        """add should register an IntervalSchedule entry."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry = scheduler.add("test", mock_actor, schedule)

        assert entry.name == "test"
        assert entry.actor is mock_actor
        assert entry.schedule is schedule

    def test_add_with_cron(self, mock_actor, clean_registry):
        """add should register a CronSchedule entry."""
        scheduler = Scheduler()
        schedule = CronSchedule("* * * * *")

        entry = scheduler.add("test", mock_actor, schedule)

        assert entry.name == "test"
        assert entry.schedule is schedule

    def test_add_with_args_kwargs(self, mock_actor, clean_registry):
        """add should pass args and kwargs to registry."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry = scheduler.add("test", mock_actor, schedule, args=(1, 2), kwargs={"key": "value"})

        assert entry.args == (1, 2)
        assert entry.kwargs == {"key": "value"}

    def test_add_disabled(self, mock_actor, clean_registry):
        """add should register disabled entries."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry = scheduler.add("test", mock_actor, schedule, enabled=False)

        assert entry.enabled is False

    def test_add_with_replace(self, mock_actor, clean_registry):
        """add with replace=True should overwrite existing entry."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry1 = scheduler.add("test", mock_actor, schedule)
        entry2 = scheduler.add("test", mock_actor, schedule, replace=True)

        assert len(scheduler) == 1
        assert entry2 is not entry1


class TestSchedulerRemove:
    """Test Scheduler.remove method."""

    def test_remove_existing(self, mock_actor, clean_registry):
        """remove should unregister an entry."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        scheduler.add("test", mock_actor, schedule)
        assert len(scheduler) == 1

        scheduler.remove("test")
        assert len(scheduler) == 0

    def test_remove_nonexistent(self, clean_registry):
        """remove should be no-op for non-existent names."""
        scheduler = Scheduler()
        scheduler.remove("nonexistent")  # Should not raise


class TestSchedulerRunNow:
    """Test Scheduler.run_now method."""

    def test_run_now_enqueues_task(self, mock_actor, clean_registry):
        """run_now should call actor.send() immediately."""
        scheduler = Scheduler()

        scheduler.run_now(mock_actor, 1, 2, key="value")

        mock_actor.send.assert_called_once_with(1, 2, key="value")

    def test_run_now_with_no_args(self, mock_actor, clean_registry):
        """run_now should work with no arguments."""
        scheduler = Scheduler()

        scheduler.run_now(mock_actor)

        mock_actor.send.assert_called_once_with()

    def test_run_now_plain_function_raises(self, clean_registry):
        """run_now should raise TypeError for non-actors."""
        scheduler = Scheduler()

        def plain_function():
            pass

        with pytest.raises(TypeError, match="not a Dramatiq actor"):
            scheduler.run_now(plain_function)

    def test_run_now_error_message_shows_function_name(self, clean_registry):
        """Error message should include function name."""
        scheduler = Scheduler()

        def my_function():
            pass

        with pytest.raises(TypeError, match="my_function"):
            scheduler.run_now(my_function)


class TestSchedulerTick:
    """Test Scheduler.tick method."""

    def test_tick_empty_registry(self, clean_registry):
        """tick should return empty list for empty registry."""
        scheduler = Scheduler()
        now = datetime.now(UTC)

        enqueued = scheduler.tick(now)

        assert enqueued == []

    def test_tick_enqueues_due_tasks(self, mock_actor, clean_registry):
        """tick should enqueue all due tasks."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        scheduler.add("test", mock_actor, schedule)

        now = datetime.now(UTC)
        enqueued = scheduler.tick(now)

        assert enqueued == ["test"]
        mock_actor.send.assert_called_once()

    def test_tick_updates_last_run_at(self, mock_actor, clean_registry):
        """tick should update last_run_at for enqueued tasks."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry = scheduler.add("test", mock_actor, schedule)
        assert entry.last_run_at is None

        now = datetime.now(UTC)
        scheduler.tick(now)

        assert entry.last_run_at == now

    def test_tick_skips_not_due_tasks(self, mock_actor, clean_registry):
        """tick should skip tasks that are not due."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry = scheduler.add("test", mock_actor, schedule)
        entry.last_run_at = datetime.now(UTC)

        # Tick immediately after last run
        enqueued = scheduler.tick(entry.last_run_at)

        assert enqueued == []
        mock_actor.send.assert_not_called()

    def test_tick_with_args_kwargs(self, mock_actor, clean_registry):
        """tick should pass args and kwargs to actor.send()."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        scheduler.add("test", mock_actor, schedule, args=(1, 2), kwargs={"key": "value"})

        now = datetime.now(UTC)
        scheduler.tick(now)

        mock_actor.send.assert_called_once_with(1, 2, key="value")

    def test_tick_handles_actor_send_error(self, mock_actor, clean_registry):
        """tick should catch and log errors from actor.send()."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        mock_actor.send.side_effect = Exception("Send failed")
        scheduler.add("test", mock_actor, schedule)

        now = datetime.now(UTC)
        with patch("openviper.tasks.core.logger") as mock_logger:
            enqueued = scheduler.tick(now)

        # Task should not be in enqueued list
        assert enqueued == []
        # Error should be logged
        assert mock_logger.error.called

    def test_tick_default_now(self, mock_actor, clean_registry):
        """tick should use current time when now is None."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        scheduler.add("test", mock_actor, schedule)

        enqueued = scheduler.tick()  # No explicit now

        assert enqueued == ["test"]

    def test_tick_multiple_due_tasks(self, clean_registry):
        """tick should enqueue all due tasks and sort names."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        actor1 = MagicMock()
        actor1.send = MagicMock()
        actor2 = MagicMock()
        actor2.send = MagicMock()
        actor3 = MagicMock()
        actor3.send = MagicMock()

        scheduler.add("zebra", actor1, schedule)
        scheduler.add("alpha", actor2, schedule)
        scheduler.add("beta", actor3, schedule)

        now = datetime.now(UTC)
        enqueued = scheduler.tick(now)

        # Should be sorted
        assert enqueued == ["alpha", "beta", "zebra"]
        actor1.send.assert_called_once()
        actor2.send.assert_called_once()
        actor3.send.assert_called_once()


class TestSchedulerIntrospection:
    """Test Scheduler introspection methods."""

    def test_get_registry(self, clean_registry):
        """get_registry should return the internal registry."""
        scheduler = Scheduler()
        assert isinstance(scheduler.get_registry(), ScheduleRegistry)
        assert scheduler.get_registry() is scheduler._registry

    def test_all_entries(self, mock_actor, clean_registry):
        """all_entries should return all registered entries."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        entry1 = scheduler.add("test1", mock_actor, schedule)
        entry2 = scheduler.add("test2", mock_actor, schedule)

        entries = scheduler.all_entries()
        assert len(entries) == 2
        assert entry1 in entries
        assert entry2 in entries

    def test_len(self, mock_actor, clean_registry):
        """__len__ should return number of entries."""
        scheduler = Scheduler()
        schedule = IntervalSchedule(60)

        assert len(scheduler) == 0

        scheduler.add("test1", mock_actor, schedule)
        assert len(scheduler) == 1

        scheduler.add("test2", mock_actor, schedule)
        assert len(scheduler) == 2

    def test_repr(self, clean_registry):
        """__repr__ should show entry count."""
        scheduler = Scheduler()
        assert repr(scheduler) == "Scheduler(entries=0)"

        schedule = IntervalSchedule(60)
        mock_actor = MagicMock()
        scheduler.add("test", mock_actor, schedule)

        assert repr(scheduler) == "Scheduler(entries=1)"
