"""Tests for openviper/tasks/registry.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from openviper.tasks.registry import ScheduleEntry, ScheduleRegistry, get_registry, reset_registry
from openviper.tasks.schedule import IntervalSchedule


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    reset_registry()
    yield
    reset_registry()


def _make_actor(name: str = "my_actor") -> MagicMock:
    actor = MagicMock()
    actor.actor_name = name
    actor.send = MagicMock()
    return actor


def _make_schedule(due: bool = True) -> MagicMock:
    sched = MagicMock()
    sched.is_due.return_value = due
    return sched


# ---------------------------------------------------------------------------
# ScheduleEntry
# ---------------------------------------------------------------------------


class TestScheduleEntry:
    def test_is_due_enabled(self) -> None:
        sched = _make_schedule(due=True)
        entry = ScheduleEntry(name="t", actor=_make_actor(), schedule=sched)
        assert entry.is_due() is True

    def test_is_due_disabled(self) -> None:
        sched = _make_schedule(due=True)
        entry = ScheduleEntry(name="t", actor=_make_actor(), schedule=sched, enabled=False)
        assert entry.is_due() is False

    def test_is_due_not_due(self) -> None:
        sched = _make_schedule(due=False)
        entry = ScheduleEntry(name="t", actor=_make_actor(), schedule=sched)
        assert entry.is_due() is False

    def test_is_due_passes_now(self) -> None:
        sched = _make_schedule(due=True)
        entry = ScheduleEntry(name="t", actor=_make_actor(), schedule=sched)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        entry.is_due(now)
        sched.is_due.assert_called_once_with(entry.last_run_at, now)

    def test_is_due_defaults_now(self) -> None:
        sched = _make_schedule(due=True)
        entry = ScheduleEntry(name="t", actor=_make_actor(), schedule=sched)
        entry.is_due()
        sched.is_due.assert_called_once()

    def test_defaults(self) -> None:
        sched = _make_schedule()
        entry = ScheduleEntry(name="x", actor=_make_actor(), schedule=sched)
        assert entry.args == ()
        assert entry.kwargs == {}
        assert entry.enabled is True
        assert entry.last_run_at is None


# ---------------------------------------------------------------------------
# ScheduleRegistry
# ---------------------------------------------------------------------------


class TestScheduleRegistry:
    def test_register_basic(self) -> None:
        reg = ScheduleRegistry()
        actor = _make_actor()
        sched = IntervalSchedule(60)
        entry = reg.register("task1", actor, sched)
        assert entry.name == "task1"
        assert len(reg) == 1

    def test_register_duplicate_raises(self) -> None:
        reg = ScheduleRegistry()
        actor = _make_actor()
        sched = IntervalSchedule(60)
        reg.register("task1", actor, sched)
        with pytest.raises(ValueError, match="already exists"):
            reg.register("task1", actor, sched)

    def test_register_replace(self) -> None:
        reg = ScheduleRegistry()
        actor = _make_actor()
        sched = IntervalSchedule(60)
        reg.register("task1", actor, sched)
        entry2 = reg.register("task1", actor, sched, replace=True)
        assert entry2.name == "task1"
        assert len(reg) == 1

    def test_register_kwargs_defaults_to_empty(self) -> None:
        reg = ScheduleRegistry()
        entry = reg.register("t", _make_actor(), IntervalSchedule(60))
        assert entry.kwargs == {}

    def test_register_with_args_kwargs(self) -> None:
        reg = ScheduleRegistry()
        entry = reg.register(
            "t", _make_actor(), IntervalSchedule(60), args=(1, 2), kwargs={"k": "v"}
        )
        assert entry.args == (1, 2)
        assert entry.kwargs == {"k": "v"}

    def test_register_disabled(self) -> None:
        reg = ScheduleRegistry()
        entry = reg.register("t", _make_actor(), IntervalSchedule(60), enabled=False)
        assert entry.enabled is False

    def test_unregister_existing(self) -> None:
        reg = ScheduleRegistry()
        reg.register("t", _make_actor(), IntervalSchedule(60))
        reg.unregister("t")
        assert len(reg) == 0

    def test_unregister_nonexistent(self) -> None:
        reg = ScheduleRegistry()
        reg.unregister("nonexistent")  # no-op, should not raise

    def test_get_existing(self) -> None:
        reg = ScheduleRegistry()
        reg.register("t", _make_actor(), IntervalSchedule(60))
        entry = reg.get("t")
        assert entry is not None
        assert entry.name == "t"

    def test_get_nonexistent(self) -> None:
        reg = ScheduleRegistry()
        assert reg.get("nope") is None

    def test_all_entries(self) -> None:
        reg = ScheduleRegistry()
        reg.register("a", _make_actor(), IntervalSchedule(60))
        reg.register("b", _make_actor(), IntervalSchedule(120))
        entries = reg.all_entries()
        assert len(entries) == 2

    def test_all_due(self) -> None:
        reg = ScheduleRegistry()
        due_sched = _make_schedule(due=True)
        not_due_sched = _make_schedule(due=False)
        reg.register("due_task", _make_actor(), due_sched)
        reg.register("not_due_task", _make_actor(), not_due_sched)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        due = reg.all_due(now)
        assert len(due) == 1
        assert due[0].name == "due_task"

    def test_all_due_defaults_now(self) -> None:
        reg = ScheduleRegistry()
        sched = _make_schedule(due=True)
        reg.register("t", _make_actor(), sched)
        due = reg.all_due()
        assert len(due) == 1

    def test_clear(self) -> None:
        reg = ScheduleRegistry()
        reg.register("a", _make_actor(), IntervalSchedule(60))
        reg.register("b", _make_actor(), IntervalSchedule(60))
        reg.clear()
        assert len(reg) == 0

    def test_len(self) -> None:
        reg = ScheduleRegistry()
        assert len(reg) == 0
        reg.register("t", _make_actor(), IntervalSchedule(60))
        assert len(reg) == 1

    def test_contains(self) -> None:
        reg = ScheduleRegistry()
        reg.register("t", _make_actor(), IntervalSchedule(60))
        assert "t" in reg
        assert "nope" not in reg


# ---------------------------------------------------------------------------
# get_registry singleton
# ---------------------------------------------------------------------------


class TestGetRegistry:
    def test_returns_registry(self) -> None:
        reg = get_registry()
        assert isinstance(reg, ScheduleRegistry)

    def test_singleton(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_creates_new(self) -> None:
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()
        assert r1 is not r2
