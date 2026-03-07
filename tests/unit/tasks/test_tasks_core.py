from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from openviper.tasks.core import Scheduler
from openviper.tasks.registry import ScheduleRegistry, reset_registry


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


def _make_schedule(is_due: bool = True) -> MagicMock:
    sched = MagicMock()
    sched.is_due.return_value = is_due
    return sched


def _make_actor(name: str = "actor") -> MagicMock:
    actor = MagicMock()
    actor.actor_name = name
    actor.send = MagicMock()
    return actor


# ── __init__ ───────────────────────────────────────────────────────────────


def test_scheduler_with_custom_registry():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    assert scheduler._registry is custom_reg


def test_scheduler_default_registry_uses_singleton():
    from openviper.tasks.registry import get_registry

    scheduler = Scheduler()
    assert scheduler._registry is get_registry()


# ── add ────────────────────────────────────────────────────────────────────


def test_scheduler_add_registers_entry():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    actor = _make_actor()
    entry = scheduler.add("weekly", actor, _make_schedule())
    assert entry.name == "weekly"
    assert "weekly" in custom_reg


# ── remove ─────────────────────────────────────────────────────────────────


def test_scheduler_remove_unregisters_entry():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    actor = _make_actor()
    scheduler.add("my_task", actor, _make_schedule())
    assert "my_task" in custom_reg
    scheduler.remove("my_task")
    assert "my_task" not in custom_reg


# ── run_now ────────────────────────────────────────────────────────────────


def test_scheduler_run_now_raises_type_error_for_plain_function():
    scheduler = Scheduler()

    def plain_fn():
        pass

    with pytest.raises(TypeError, match="@task"):
        scheduler.run_now(plain_fn)


def test_scheduler_run_now_sends_actor():
    scheduler = Scheduler()
    actor = _make_actor("my_actor")
    scheduler.run_now(actor, 1, 2, key="value")
    actor.send.assert_called_once_with(1, 2, key="value")


def test_scheduler_run_now_sends_actor_no_args():
    scheduler = Scheduler()
    actor = _make_actor()
    scheduler.run_now(actor)
    actor.send.assert_called_once_with()


# ── tick ───────────────────────────────────────────────────────────────────


def test_scheduler_tick_enqueues_due_entries():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    actor_a = _make_actor("actor_a")
    actor_b = _make_actor("actor_b")
    now = datetime.now(UTC)

    custom_reg.register("task_a", actor_a, _make_schedule(True))
    custom_reg.register("task_b", actor_b, _make_schedule(False))

    enqueued = scheduler.tick(now=now)
    actor_a.send.assert_called_once()
    actor_b.send.assert_not_called()
    assert enqueued == ["task_a"]


def test_scheduler_tick_handles_send_failure():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    failing_actor = _make_actor("failing")
    failing_actor.send.side_effect = RuntimeError("broker down")

    custom_reg.register("failing_task", failing_actor, _make_schedule(True))

    now = datetime.now(UTC)
    enqueued = scheduler.tick(now=now)

    # tick() should not raise — failed entry is excluded from result
    assert enqueued == []


def test_scheduler_tick_returns_sorted_names():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    for name in ["z_task", "a_task", "m_task"]:
        custom_reg.register(name, _make_actor(name), _make_schedule(True))

    enqueued = scheduler.tick()
    assert enqueued == sorted(enqueued)


def test_scheduler_tick_uses_utcnow_by_default():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    custom_reg.register("t", _make_actor(), _make_schedule(True))
    enqueued = scheduler.tick()
    assert enqueued == ["t"]


# ── Introspection ──────────────────────────────────────────────────────────


def test_scheduler_get_registry():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    assert scheduler.get_registry() is custom_reg


def test_scheduler_all_entries():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    actor = _make_actor()
    custom_reg.register("e1", actor, _make_schedule())
    custom_reg.register("e2", actor, _make_schedule())
    entries = scheduler.all_entries()
    assert len(entries) == 2


def test_scheduler_len():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    assert len(scheduler) == 0
    custom_reg.register("t", _make_actor(), _make_schedule())
    assert len(scheduler) == 1


def test_scheduler_repr():
    custom_reg = ScheduleRegistry()
    scheduler = Scheduler(registry=custom_reg)
    r = repr(scheduler)
    assert "Scheduler" in r
    assert "entries=0" in r

    custom_reg.register("t", _make_actor(), _make_schedule())
    r2 = repr(scheduler)
    assert "entries=1" in r2
