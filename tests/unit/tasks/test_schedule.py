"""Tests for openviper/tasks/schedule.py — IntervalSchedule, CronSchedule, _expand_field."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.schedule import (
    CronSchedule,
    IntervalSchedule,
    _expand_field,
    _try_import_croniter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _dt(year=2024, month=1, day=1, hour=0, minute=0, second=0, tz=_UTC):
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


# ---------------------------------------------------------------------------
# _try_import_croniter
# ---------------------------------------------------------------------------


def test_try_import_croniter_returns_false_when_not_installed():
    """Without croniter installed the function returns False."""
    # In this test environment croniter is not installed.
    result = _try_import_croniter()
    assert result is False


def test_try_import_croniter_returns_true_when_installed():
    """Line 265: returns True when croniter IS importable."""
    mock_mod = MagicMock()
    with patch.dict(sys.modules, {"croniter": mock_mod}):
        result = _try_import_croniter()
    assert result is True


# ---------------------------------------------------------------------------
# _expand_field
# ---------------------------------------------------------------------------


def test_expand_field_star():
    """'*' expands to full range."""
    assert _expand_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}


def test_expand_field_single_value():
    """Single integer token."""
    assert _expand_field("3", 0, 59) == {3}


def test_expand_field_range():
    """'1-3' expands to {1, 2, 3}."""
    assert _expand_field("1-3", 0, 59) == {1, 2, 3}


def test_expand_field_star_step():
    """'*/15' for minutes gives {0, 15, 30, 45}."""
    result = _expand_field("*/15", 0, 59)
    assert result == {0, 15, 30, 45}


def test_expand_field_range_step():
    """'0-30/10' gives {0, 10, 20, 30}."""
    assert _expand_field("0-30/10", 0, 59) == {0, 10, 20, 30}


def test_expand_field_value_step():
    """'5/20' with hi=59 gives {5, 25, 45}."""
    assert _expand_field("5/20", 0, 59) == {5, 25, 45}


def test_expand_field_comma_separated():
    """Comma-separated values are unioned."""
    assert _expand_field("1,3,5", 0, 59) == {1, 3, 5}


def test_expand_field_comma_with_range():
    """Comma separating a range and a value."""
    assert _expand_field("1-3,7", 0, 59) == {1, 2, 3, 7}


def test_expand_field_step_zero_raises_value_error():
    """Step of 0 raises ValueError."""
    with pytest.raises(ValueError, match="step must be >= 1"):
        _expand_field("*/0", 0, 59)


# ---------------------------------------------------------------------------
# IntervalSchedule — __init__ validation (lines 82-84)
# ---------------------------------------------------------------------------


def test_interval_schedule_raises_on_zero_seconds():
    """Lines 82-84: seconds=0 raises ValueError."""
    with pytest.raises(ValueError, match="must be > 0"):
        IntervalSchedule(0)


def test_interval_schedule_raises_on_negative_seconds():
    """seconds < 0 also raises ValueError."""
    with pytest.raises(ValueError, match="must be > 0"):
        IntervalSchedule(-5)


def test_interval_schedule_positive_seconds_ok():
    s = IntervalSchedule(30)
    assert s.seconds == 30


# ---------------------------------------------------------------------------
# IntervalSchedule — is_due (lines 88-97)
# ---------------------------------------------------------------------------


def test_interval_schedule_is_due_last_run_none():
    """Line 88-89: None last_run_at → always due."""
    s = IntervalSchedule(60)
    assert s.is_due(None) is True


def test_interval_schedule_is_due_defaults_now_to_utcnow():
    """Line 90: when now=None, datetime.now(utc) is used."""
    s = IntervalSchedule(1)
    past = datetime.now(_UTC) - timedelta(seconds=10)
    assert s.is_due(past) is True  # 10s > 1s threshold


def test_interval_schedule_is_due_when_elapsed():
    """elapsed >= seconds → True."""
    s = IntervalSchedule(60)
    last = _dt(minute=0)
    now = _dt(minute=2)  # 120s elapsed
    assert s.is_due(last, now) is True


def test_interval_schedule_not_due_yet():
    """elapsed < seconds → False."""
    s = IntervalSchedule(300)
    last = _dt(minute=0)
    now = _dt(minute=1)  # only 60s elapsed
    assert s.is_due(last, now) is False


def test_interval_schedule_naive_now_gets_utc_tzinfo():
    """Line 92-93: naive 'now' gets UTC tzinfo attached."""
    s = IntervalSchedule(1)
    naive_last = datetime(2024, 1, 1, 0, 0, 0)  # no tzinfo
    naive_now = datetime(2024, 1, 1, 0, 0, 10)  # 10s later, no tzinfo
    assert s.is_due(naive_last, naive_now) is True


def test_interval_schedule_naive_last_run_at_gets_utc_tzinfo():
    """Line 94-95: naive last_run_at gets UTC tzinfo attached."""
    s = IntervalSchedule(1)
    naive_last = datetime(2024, 1, 1, 0, 0, 0)  # no tzinfo
    aware_now = datetime(2024, 1, 1, 0, 0, 10, tzinfo=_UTC)
    assert s.is_due(naive_last, aware_now) is True


def test_interval_schedule_repr():
    assert repr(IntervalSchedule(90)) == "IntervalSchedule(seconds=90)"


# ---------------------------------------------------------------------------
# CronSchedule — __init__ and _parse (lines 175-192)
# ---------------------------------------------------------------------------


def test_cron_schedule_init_strips_whitespace():
    """Line 175: expr is stripped of leading/trailing whitespace."""
    s = CronSchedule("  * * * * *  ")
    assert s.expr == "* * * * *"


def test_cron_schedule_init_parses_fields_when_no_croniter():
    """Lines 178-179: when croniter not available, _fields is populated."""
    s = CronSchedule("*/5 * * * *")
    assert s._use_croniter is False
    assert s._fields is not None
    # minute field: 0,5,10,...,55
    assert 0 in s._fields["minute"]
    assert 5 in s._fields["minute"]
    assert 1 not in s._fields["minute"]


def test_cron_schedule_parse_wrong_field_count_raises():
    """Lines 187-191: non-5-field expression raises ValueError."""
    with pytest.raises(ValueError, match="5-field"):
        CronSchedule("* * * *")  # only 4 fields


def test_cron_schedule_parse_all_star():
    """'* * * * *' matches every minute/hour/dom/month/dow."""
    s = CronSchedule("* * * * *")
    assert s._fields is not None
    assert len(s._fields["minute"]) == 60
    assert len(s._fields["hour"]) == 24


# ---------------------------------------------------------------------------
# CronSchedule — _stdlib_is_due (lines 199-209)
# ---------------------------------------------------------------------------


def test_cron_schedule_stdlib_is_due_true():
    """Lines 199-209: all fields match → True."""
    # "* * * * *" matches any time
    s = CronSchedule("* * * * *")
    now = _dt(month=3, day=15, hour=10, minute=30)
    assert s._stdlib_is_due(None, now) is True


def test_cron_schedule_stdlib_is_due_false_wrong_minute():
    """Specific minute that doesn't match → False."""
    s = CronSchedule("0 * * * *")  # only minute=0
    now = _dt(minute=5)  # minute=5 not in {0}
    assert s._stdlib_is_due(None, now) is False


def test_cron_schedule_stdlib_is_due_dow_conversion():
    """Day-of-week conversion: cron_dow = (python_weekday + 1) % 7."""
    # Monday is python weekday 0, cron dow 1
    # CronSchedule "* * * * 1" → Monday only
    s = CronSchedule("* * * * 1")
    # datetime(2024, 1, 1) is a Monday → python weekday=0 → cron_dow=1
    monday = datetime(2024, 1, 1, 12, 0, tzinfo=_UTC)
    tuesday = datetime(2024, 1, 2, 12, 0, tzinfo=_UTC)
    assert s._stdlib_is_due(None, monday) is True
    assert s._stdlib_is_due(None, tuesday) is False


# ---------------------------------------------------------------------------
# CronSchedule — is_due (lines 223-229)
# ---------------------------------------------------------------------------


def test_cron_schedule_is_due_defaults_now_to_utcnow():
    """Line 223: now=None → datetime.now(utc) is used (doesn't raise)."""
    s = CronSchedule("* * * * *")
    # Should not raise; result depends on current time
    result = s.is_due(None)
    assert isinstance(result, bool)


def test_cron_schedule_is_due_naive_now_gets_tzinfo():
    """Lines 224-225: naive 'now' gets UTC tzinfo."""
    s = CronSchedule("* * * * *")
    naive = datetime(2024, 1, 1, 0, 0)  # no tzinfo
    # Should not raise and should call _stdlib_is_due
    result = s.is_due(None, naive)
    assert result is True  # "* * * * *" always matches


def test_cron_schedule_is_due_dispatches_to_stdlib():
    """Line 229: when _use_croniter is False, _stdlib_is_due is called."""
    s = CronSchedule("0 0 * * *")  # midnight only
    midnight = _dt(hour=0, minute=0)
    noon = _dt(hour=12, minute=0)
    assert s.is_due(None, midnight) is True
    assert s.is_due(None, noon) is False


def test_cron_schedule_repr():
    assert repr(CronSchedule("*/5 * * * *")) == "CronSchedule('*/5 * * * *')"


# ---------------------------------------------------------------------------
# CronSchedule — _croniter_is_due (lines 232-249)
# ---------------------------------------------------------------------------


def _make_croniter_module(next_run: datetime) -> MagicMock:
    """Build a fake `croniter` module whose instance returns *next_run* from get_next()."""
    mock_instance = MagicMock()
    mock_instance.get_next.return_value = next_run

    mock_mod = MagicMock()
    mock_mod.croniter.return_value = mock_instance
    return mock_mod


def test_croniter_is_due_last_run_none_returns_true():
    """Line 235-237: last_run_at=None → True immediately (never run before)."""
    mock_croniter_mod = _make_croniter_module(_dt(minute=5))

    with patch.dict(sys.modules, {"croniter": mock_croniter_mod}):
        s = CronSchedule("* * * * *")
        assert s._use_croniter is True
        now = _dt(minute=0)
        assert s._croniter_is_due(None, now) is True

    # croniter.croniter was NOT called (short-circuit)
    mock_croniter_mod.croniter.assert_not_called()


def test_croniter_is_due_not_yet_due():
    """Lines 240-244: now < next_run → False."""
    future_next = _dt(minute=10)
    mock_croniter_mod = _make_croniter_module(future_next)

    with patch.dict(sys.modules, {"croniter": mock_croniter_mod}):
        s = CronSchedule("*/10 * * * *")
        now = _dt(minute=5)
        last = _dt(minute=0)
        assert s._croniter_is_due(last, now) is False


def test_croniter_is_due_at_or_after_next_run():
    """Lines 240-244: now >= next_run → True."""
    past_next = _dt(minute=3)
    mock_croniter_mod = _make_croniter_module(past_next)

    with patch.dict(sys.modules, {"croniter": mock_croniter_mod}):
        s = CronSchedule("*/5 * * * *")
        now = _dt(minute=5)
        last = _dt(minute=0)
        assert s._croniter_is_due(last, now) is True


def test_croniter_is_due_naive_last_run_at_gets_tz():
    """Lines 238-239: naive last_run_at gets UTC tzinfo before passing to croniter."""
    next_run = _dt(minute=5)
    mock_croniter_mod = _make_croniter_module(next_run)

    with patch.dict(sys.modules, {"croniter": mock_croniter_mod}):
        s = CronSchedule("*/5 * * * *")
        naive_last = datetime(2024, 1, 1, 0, 0)  # no tzinfo
        now = _dt(minute=0)
        # Should not raise due to tz subtraction; result depends on next_run vs now
        s._croniter_is_due(naive_last, now)

    # croniter was called with a tz-aware last_run_at
    call_args = mock_croniter_mod.croniter.call_args
    passed_last = call_args[0][1]
    assert passed_last.tzinfo is not None


def test_croniter_is_due_naive_next_run_gets_tz():
    """Lines 242-243: naive next_run from get_next() gets UTC tzinfo."""
    naive_next = datetime(2024, 1, 1, 0, 5)  # no tzinfo
    mock_croniter_mod = _make_croniter_module(naive_next)

    with patch.dict(sys.modules, {"croniter": mock_croniter_mod}):
        s = CronSchedule("*/5 * * * *")
        last = _dt(minute=0)
        now = _dt(minute=10)
        # Should not raise (naive next_run gets tz before comparison)
        result = s._croniter_is_due(last, now)
        assert isinstance(result, bool)


def test_croniter_is_due_exception_falls_back_to_stdlib():
    """Lines 245-249: any exception from croniter falls back to stdlib."""
    mock_mod = MagicMock()
    mock_mod.croniter.side_effect = RuntimeError("croniter broken")

    with patch.dict(sys.modules, {"croniter": mock_mod}):
        s = CronSchedule("* * * * *")
        now = _dt(minute=0)
        last = _dt(minute=0)
        # Must not raise; stdlib fallback always returns True for "* * * * *"
        result = s._croniter_is_due(last, now)
    assert result is True


def test_croniter_is_due_exception_parses_fields_when_none():
    """Lines 247-248: if _fields is None when exception occurs, they get parsed."""
    mock_mod = MagicMock()
    mock_mod.croniter.side_effect = RuntimeError("broken")

    with patch.dict(sys.modules, {"croniter": mock_mod}):
        s = CronSchedule("* * * * *")
        assert s._use_croniter is True
        # Force _fields to None to hit the parsing branch
        s._fields = None
        now = _dt(minute=0)
        last = _dt(hour=0, minute=0)
        result = s._croniter_is_due(last, now)

    assert s._fields is not None
    assert result is True


def test_cron_schedule_is_due_uses_croniter_when_available():
    """Line 228: when _use_croniter is True, _croniter_is_due is called."""
    past_next = _dt(minute=0)
    mock_mod = _make_croniter_module(past_next)

    with patch.dict(sys.modules, {"croniter": mock_mod}):
        s = CronSchedule("* * * * *")
        assert s._use_croniter is True
        now = _dt(minute=5)
        # last_run_at=None → immediate True (never-run path)
        assert s.is_due(None, now) is True
