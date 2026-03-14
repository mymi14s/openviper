"""Unit tests for openviper/tasks/schedule.py and tasks/registry.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from openviper.tasks.registry import ScheduleEntry, ScheduleRegistry, get_registry
from openviper.tasks.schedule import CronSchedule, IntervalSchedule

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_interval(seconds: float = 60.0) -> IntervalSchedule:
    return IntervalSchedule(seconds)


def make_cron(expr: str = "* * * * *") -> CronSchedule:
    return CronSchedule(expr)


def make_actor(name: str = "test_task") -> MagicMock:
    actor = MagicMock()
    actor.__name__ = name
    actor.send = MagicMock()
    return actor


def make_entry(name="test", schedule=None, actor=None, enabled=True) -> ScheduleEntry:
    return ScheduleEntry(
        name=name,
        actor=actor or make_actor(),
        schedule=schedule or make_interval(60),
        enabled=enabled,
    )


def make_registry() -> ScheduleRegistry:
    return ScheduleRegistry()


UTC_NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# IntervalSchedule
# ---------------------------------------------------------------------------


class TestIntervalSchedule:
    def test_stores_seconds(self):
        assert make_interval(120).seconds == 120

    def test_invalid_seconds_raises(self):
        with pytest.raises(ValueError):
            IntervalSchedule(0)

    def test_negative_seconds_raises(self):
        with pytest.raises(ValueError):
            IntervalSchedule(-1)

    def test_due_when_last_run_none(self):
        assert make_interval(60).is_due(None) is True

    def test_due_when_enough_time_elapsed(self):
        s = make_interval(60)
        last_run = UTC_NOW - timedelta(seconds=120)
        assert s.is_due(last_run, now=UTC_NOW) is True

    def test_not_due_when_too_soon(self):
        s = make_interval(3600)
        last_run = UTC_NOW - timedelta(seconds=10)
        assert s.is_due(last_run, now=UTC_NOW) is False

    def test_exactly_at_boundary_is_due(self):
        s = make_interval(60)
        last_run = UTC_NOW - timedelta(seconds=60)
        assert s.is_due(last_run, now=UTC_NOW) is True

    def test_repr(self):
        assert "60" in repr(make_interval(60))

    def test_naive_last_run_handled(self):
        s = make_interval(60)
        naive = datetime.now() - timedelta(seconds=120)
        result = s.is_due(naive, now=UTC_NOW)
        assert isinstance(result, bool)

    @pytest.mark.parametrize(
        "seconds,elapsed,expected",
        [
            (60, 30, False),
            (60, 60, True),
            (60, 120, True),
            (3600, 1800, False),
            (3600, 3601, True),
        ],
    )
    def test_parametrized(self, seconds, elapsed, expected):
        s = IntervalSchedule(seconds)
        last = UTC_NOW - timedelta(seconds=elapsed)
        assert s.is_due(last, now=UTC_NOW) == expected


# ---------------------------------------------------------------------------
# CronSchedule
# ---------------------------------------------------------------------------


class TestCronSchedule:
    def test_stores_expression(self):
        assert make_cron("0 8 * * *").expr == "0 8 * * *"

    def test_wildcard_due_when_never_ran(self):
        s = make_cron("* * * * *")
        assert s.is_due(None) is True

    def test_repr(self):
        r = repr(make_cron("*/5 * * * *"))
        assert "CronSchedule" in r or "*/5" in r

    def test_is_due_returns_bool(self):
        s = make_cron("* * * * *")
        last = UTC_NOW - timedelta(minutes=2)
        assert isinstance(s.is_due(last, now=UTC_NOW), bool)


# ---------------------------------------------------------------------------
# ScheduleEntry
# ---------------------------------------------------------------------------


class TestScheduleEntry:
    def test_name(self):
        assert make_entry(name="x").name == "x"

    def test_enabled_default_true(self):
        assert make_entry().enabled is True

    def test_last_run_default_none(self):
        assert make_entry().last_run_at is None

    def test_is_due_enabled_and_due(self):
        entry = make_entry(schedule=make_interval(60))
        assert entry.is_due(now=UTC_NOW) is True

    def test_not_due_when_disabled(self):
        assert make_entry(enabled=False).is_due(now=UTC_NOW) is False

    def test_args_default_empty(self):
        assert make_entry().args == ()

    def test_kwargs_default_empty(self):
        assert make_entry().kwargs == {}


# ---------------------------------------------------------------------------
# ScheduleRegistry
# ---------------------------------------------------------------------------


class TestScheduleRegistry:
    def test_register_entry(self):
        reg = make_registry()
        reg.register("t1", make_actor(), make_interval(60))
        assert reg.get("t1") is not None

    def test_register_duplicate_raises(self):
        reg = make_registry()
        reg.register("t1", make_actor(), make_interval(60))
        with pytest.raises(ValueError):
            reg.register("t1", make_actor(), make_interval(60))

    def test_register_with_replace(self):
        reg = make_registry()
        reg.register("t1", make_actor(), make_interval(60))
        reg.register("t1", make_actor(), make_interval(120), replace=True)
        assert reg.get("t1").schedule.seconds == 120

    def test_unregister(self):
        reg = make_registry()
        reg.register("t1", make_actor(), make_interval(60))
        reg.unregister("t1")
        assert reg.get("t1") is None

    def test_all_entries(self):
        reg = make_registry()
        reg.register("a", make_actor(), make_interval(60))
        reg.register("b", make_actor(), make_interval(120))
        assert len(reg.all_entries()) == 2

    def test_all_due_includes_due(self):
        reg = make_registry()
        reg.register("due_task", make_actor(), make_interval(1))
        assert len(reg.all_due(now=UTC_NOW)) >= 1

    def test_all_due_excludes_recently_ran(self):
        reg = make_registry()
        reg.register("recently_ran", make_actor(), make_interval(3600))
        reg.get("recently_ran").last_run_at = UTC_NOW
        assert not any(e.name == "recently_ran" for e in reg.all_due(now=UTC_NOW))

    def test_get_registry_singleton(self):
        assert get_registry() is get_registry()
