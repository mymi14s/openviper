"""Coverage for openviper/tasks/registry.py — ScheduleRegistry and helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from openviper.tasks.registry import (
    ScheduleEntry,
    ScheduleRegistry,
    get_registry,
    reset_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


def _make_schedule(is_due: bool = True) -> MagicMock:
    sched = MagicMock()
    sched.is_due.return_value = is_due
    return sched


# ---------------------------------------------------------------------------
# ScheduleRegistry initialisation
# ---------------------------------------------------------------------------


def test_registry_init_is_empty():
    reg = ScheduleRegistry()
    assert len(reg) == 0
    assert reg.all_entries() == []


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_register_entry_returns_entry():
    reg = ScheduleRegistry()
    actor = MagicMock()
    entry = reg.register("my_task", actor, _make_schedule())
    assert entry.name == "my_task"
    assert entry.actor is actor


def test_register_entry_updates_len_and_contains():
    reg = ScheduleRegistry()
    reg.register("t", MagicMock(), _make_schedule())
    assert len(reg) == 1
    assert "t" in reg
    assert "other" not in reg


def test_register_duplicate_raises_value_error():
    reg = ScheduleRegistry()
    reg.register("dup", MagicMock(), _make_schedule())
    with pytest.raises(ValueError, match="dup"):
        reg.register("dup", MagicMock(), _make_schedule())


def test_register_duplicate_with_replace_does_not_raise():
    reg = ScheduleRegistry()
    actor1 = MagicMock()
    actor2 = MagicMock()
    e1 = reg.register("task", actor1, _make_schedule())
    e2 = reg.register("task", actor2, _make_schedule(), replace=True)
    assert e2 is not e1
    assert e2.actor is actor2
    assert len(reg) == 1


# ---------------------------------------------------------------------------
# unregister
# ---------------------------------------------------------------------------


def test_unregister_removes_entry():
    reg = ScheduleRegistry()
    reg.register("to_remove", MagicMock(), _make_schedule())
    assert "to_remove" in reg
    reg.unregister("to_remove")
    assert "to_remove" not in reg
    assert len(reg) == 0


def test_unregister_noop_when_not_found():
    reg = ScheduleRegistry()
    reg.unregister("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_returns_registered_entry():
    reg = ScheduleRegistry()
    actor = MagicMock()
    entry = reg.register("found", actor, _make_schedule())
    assert reg.get("found") is entry


def test_get_returns_none_when_missing():
    reg = ScheduleRegistry()
    assert reg.get("missing") is None


# ---------------------------------------------------------------------------
# all_entries
# ---------------------------------------------------------------------------


def test_all_entries_returns_all():
    reg = ScheduleRegistry()
    actor = MagicMock()
    reg.register("a", actor, _make_schedule())
    reg.register("b", actor, _make_schedule())
    entries = reg.all_entries()
    assert len(entries) == 2
    assert {e.name for e in entries} == {"a", "b"}


# ---------------------------------------------------------------------------
# all_due
# ---------------------------------------------------------------------------


def test_all_due_returns_only_due_entries():
    reg = ScheduleRegistry()
    actor = MagicMock()
    now = datetime.now(UTC)
    reg.register("due_task", actor, _make_schedule(is_due=True))
    reg.register("not_due_task", actor, _make_schedule(is_due=False))
    due = reg.all_due(now)
    assert len(due) == 1
    assert due[0].name == "due_task"


def test_all_due_defaults_to_utcnow():
    reg = ScheduleRegistry()
    reg.register("t", MagicMock(), _make_schedule(is_due=True))
    # Should not raise — uses datetime.now(timezone.utc) internally
    due = reg.all_due()
    assert len(due) == 1


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_empties_registry():
    reg = ScheduleRegistry()
    actor = MagicMock()
    reg.register("x", actor, _make_schedule())
    reg.register("y", actor, _make_schedule())
    assert len(reg) == 2
    reg.clear()
    assert len(reg) == 0
    assert reg.all_entries() == []


# ---------------------------------------------------------------------------
# __len__ and __contains__
# ---------------------------------------------------------------------------


def test_len_and_contains_work_together():
    reg = ScheduleRegistry()
    assert len(reg) == 0
    assert "absent" not in reg
    reg.register("present", MagicMock(), _make_schedule())
    assert len(reg) == 1
    assert "present" in reg
    assert "absent" not in reg


# ---------------------------------------------------------------------------
# get_registry singleton and reset_registry
# ---------------------------------------------------------------------------


def test_get_registry_returns_singleton():
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


def test_reset_registry_creates_fresh_singleton():
    r1 = get_registry()
    reset_registry()
    r2 = get_registry()
    assert r1 is not r2


# ---------------------------------------------------------------------------
# ScheduleEntry.is_due
# ---------------------------------------------------------------------------


def test_schedule_entry_is_due_false_when_disabled():
    """Lines 64-65: is_due() returns False immediately for disabled entries."""
    sched = _make_schedule(is_due=True)
    entry = ScheduleEntry(name="t", actor=MagicMock(), schedule=sched, enabled=False)
    assert entry.is_due() is False
    sched.is_due.assert_not_called()


def test_schedule_entry_is_due_delegates_when_enabled():
    """Lines 66-67: is_due() delegates to schedule.is_due when enabled."""
    now = datetime.now(UTC)
    sched = _make_schedule(is_due=True)
    entry = ScheduleEntry(name="t", actor=MagicMock(), schedule=sched, enabled=True)
    assert entry.is_due(now) is True
    sched.is_due.assert_called_once()


def test_schedule_entry_is_due_uses_utcnow_by_default():
    """is_due() passes a real datetime when called without args."""
    sched = _make_schedule(is_due=False)
    entry = ScheduleEntry(name="t", actor=MagicMock(), schedule=sched, enabled=True)
    result = entry.is_due()
    assert result is False
    sched.is_due.assert_called_once()
