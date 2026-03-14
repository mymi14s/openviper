"""Unit tests for openviper.tasks.registry — Schedule entry registry."""

import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from openviper.tasks.registry import (
    ScheduleEntry,
    ScheduleRegistry,
    get_registry,
    reset_registry,
)
from openviper.tasks.schedule import IntervalSchedule


class TestScheduleEntry:
    """Test ScheduleEntry dataclass."""

    def test_creation_with_defaults(self):
        """ScheduleEntry should initialize with sensible defaults."""
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        entry = ScheduleEntry(name="test", actor=actor, schedule=schedule)

        assert entry.name == "test"
        assert entry.actor is actor
        assert entry.schedule is schedule
        assert entry.args == ()
        assert entry.kwargs == {}
        assert entry.enabled is True
        assert entry.last_run_at is None

    def test_creation_with_args_kwargs(self):
        """ScheduleEntry should store args and kwargs."""
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        entry = ScheduleEntry(
            name="test", actor=actor, schedule=schedule, args=(1, 2), kwargs={"key": "value"}
        )

        assert entry.args == (1, 2)
        assert entry.kwargs == {"key": "value"}

    def test_is_due_when_enabled(self):
        """is_due should delegate to schedule when enabled."""
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        entry = ScheduleEntry(name="test", actor=actor, schedule=schedule)

        # Never run → should be due
        assert entry.is_due() is True

    def test_is_due_when_disabled(self):
        """is_due should return False when disabled."""
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        entry = ScheduleEntry(name="test", actor=actor, schedule=schedule, enabled=False)

        assert entry.is_due() is False

    def test_is_due_with_custom_now(self):
        """is_due should accept custom now parameter."""
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        entry = ScheduleEntry(name="test", actor=actor, schedule=schedule)

        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        result = entry.is_due(now=now)
        assert isinstance(result, bool)


class TestScheduleRegistry:
    """Test ScheduleRegistry class."""

    def test_init_empty(self):
        """New registry should be empty."""
        registry = ScheduleRegistry()
        assert len(registry) == 0
        assert registry.all_entries() == []

    def test_register_entry(self):
        """register should add an entry."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        entry = registry.register("test", actor, schedule)

        assert len(registry) == 1
        assert entry.name == "test"
        assert entry.actor is actor
        assert entry.schedule is schedule

    def test_register_with_args_kwargs(self):
        """register should store args and kwargs."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        entry = registry.register("test", actor, schedule, args=(1, 2), kwargs={"key": "value"})

        assert entry.args == (1, 2)
        assert entry.kwargs == {"key": "value"}

    def test_register_duplicate_raises(self):
        """register should raise ValueError for duplicate names."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        registry.register("test", actor, schedule)

        with pytest.raises(ValueError, match="already exists"):
            registry.register("test", actor, schedule)

    def test_register_duplicate_with_replace(self):
        """register with replace=True should overwrite existing entry."""
        registry = ScheduleRegistry()
        actor1 = MagicMock()
        actor2 = MagicMock()
        schedule = IntervalSchedule(60)

        entry1 = registry.register("test", actor1, schedule)
        entry2 = registry.register("test", actor2, schedule, replace=True)

        assert len(registry) == 1
        assert entry2.actor is actor2
        assert registry.get("test") is entry2

    def test_unregister_existing(self):
        """unregister should remove an entry."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        registry.register("test", actor, schedule)
        assert len(registry) == 1

        registry.unregister("test")
        assert len(registry) == 0

    def test_unregister_nonexistent(self):
        """unregister should be a no-op for non-existent names."""
        registry = ScheduleRegistry()
        registry.unregister("nonexistent")  # Should not raise

    def test_get_existing(self):
        """get should return entry by name."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        entry = registry.register("test", actor, schedule)
        assert registry.get("test") is entry

    def test_get_nonexistent(self):
        """get should return None for non-existent names."""
        registry = ScheduleRegistry()
        assert registry.get("nonexistent") is None

    def test_all_entries(self):
        """all_entries should return all registered entries."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        entry1 = registry.register("test1", actor, schedule)
        entry2 = registry.register("test2", actor, schedule)

        entries = registry.all_entries()
        assert len(entries) == 2
        assert entry1 in entries
        assert entry2 in entries

    def test_all_due_empty_registry(self):
        """all_due should return empty list for empty registry."""
        registry = ScheduleRegistry()
        now = datetime.now(UTC)
        assert registry.all_due(now) == []

    def test_all_due_filters_by_schedule(self):
        """all_due should only return entries that are due."""
        registry = ScheduleRegistry()
        actor = MagicMock()

        # One that's due (never run)
        schedule1 = IntervalSchedule(60)
        entry1 = registry.register("due", actor, schedule1)

        # One that's not due (just ran)
        schedule2 = IntervalSchedule(60)
        entry2 = registry.register("not_due", actor, schedule2)
        entry2.last_run_at = datetime.now(UTC)

        now = datetime.now(UTC)
        due_entries = registry.all_due(now)

        assert entry1 in due_entries
        assert entry2 not in due_entries

    def test_all_due_respects_enabled_flag(self):
        """all_due should skip disabled entries."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        registry.register("test", actor, schedule, enabled=False)

        now = datetime.now(UTC)
        due_entries = registry.all_due(now)

        assert len(due_entries) == 0

    def test_clear(self):
        """clear should remove all entries."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        registry.register("test1", actor, schedule)
        registry.register("test2", actor, schedule)
        assert len(registry) == 2

        registry.clear()
        assert len(registry) == 0

    def test_contains(self):
        """__contains__ should check if name is registered."""
        registry = ScheduleRegistry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)

        registry.register("test", actor, schedule)

        assert "test" in registry
        assert "other" not in registry


class TestGetRegistry:
    """Test module-level singleton access."""

    def test_get_registry_returns_singleton(self):
        """get_registry should return the same instance."""
        reset_registry()  # Start fresh
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_reset_registry(self):
        """reset_registry should clear the singleton."""
        reg1 = get_registry()
        actor = MagicMock()
        schedule = IntervalSchedule(60)
        reg1.register("test", actor, schedule)

        reset_registry()

        reg2 = get_registry()
        assert len(reg2) == 0


class TestGetRegistryThreadSafety:
    """get_registry must be safe under concurrent access."""

    def test_concurrent_access_returns_same_instance(self):
        """Multiple threads calling get_registry concurrently must all get the same object."""

        reset_registry()
        results: list = []
        errors: list = []

        def worker():
            try:
                results.append(get_registry())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20
        first = results[0]
        assert all(
            r is first for r in results
        ), "All threads must receive the same registry instance"

    def test_reset_then_get_returns_new_instance(self):
        """reset_registry followed by get_registry must produce a fresh (empty) registry."""
        reg1 = get_registry()
        reg1.register("entry", MagicMock(), IntervalSchedule(60))

        reset_registry()
        reg2 = get_registry()

        assert reg2 is not reg1
        assert len(reg2) == 0
