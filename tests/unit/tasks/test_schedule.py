"""Tests for openviper/tasks/schedule.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.schedule import (
    CronSchedule,
    IntervalSchedule,
    _expand_field,
    _try_import_croniter,
)

# ---------------------------------------------------------------------------
# _expand_field
# ---------------------------------------------------------------------------


class TestExpandField:
    def test_star_wildcard(self) -> None:
        result = _expand_field("*", 0, 5)
        assert result == {0, 1, 2, 3, 4, 5}

    def test_single_value(self) -> None:
        assert _expand_field("3", 0, 59) == {3}

    def test_range(self) -> None:
        assert _expand_field("1-3", 0, 59) == {1, 2, 3}

    def test_step_with_star(self) -> None:
        assert _expand_field("*/2", 0, 6) == {0, 2, 4, 6}

    def test_step_with_range(self) -> None:
        assert _expand_field("0-6/2", 0, 6) == {0, 2, 4, 6}

    def test_step_with_value(self) -> None:
        result = _expand_field("1/2", 0, 5)
        assert result == {1, 3, 5}

    def test_comma_separated(self) -> None:
        assert _expand_field("1,3,5", 0, 59) == {1, 3, 5}

    def test_comma_with_range(self) -> None:
        assert _expand_field("1-3,7", 0, 59) == {1, 2, 3, 7}

    def test_invalid_step_zero(self) -> None:
        with pytest.raises(ValueError, match="step must be >= 1"):
            _expand_field("*/0", 0, 59)

    def test_invalid_step_negative(self) -> None:
        with pytest.raises(ValueError, match="step must be >= 1"):
            _expand_field("*/-1", 0, 59)


# ---------------------------------------------------------------------------
# IntervalSchedule
# ---------------------------------------------------------------------------


class TestIntervalSchedule:
    def test_valid_seconds(self) -> None:
        sched = IntervalSchedule(60)
        assert sched.seconds == 60

    def test_invalid_seconds_zero(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            IntervalSchedule(0)

    def test_invalid_seconds_negative(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            IntervalSchedule(-1)

    def test_is_due_none_last_run(self) -> None:
        sched = IntervalSchedule(60)
        assert sched.is_due(None) is True

    def test_is_due_elapsed_enough(self) -> None:
        sched = IntervalSchedule(60)
        last = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        now = datetime(2024, 1, 1, 0, 1, 1, tzinfo=UTC)
        assert sched.is_due(last, now) is True

    def test_is_due_not_elapsed(self) -> None:
        sched = IntervalSchedule(60)
        last = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        now = datetime(2024, 1, 1, 0, 0, 30, tzinfo=UTC)
        assert sched.is_due(last, now) is False

    def test_is_due_exactly_elapsed(self) -> None:
        sched = IntervalSchedule(60)
        last = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        now = datetime(2024, 1, 1, 0, 1, 0, tzinfo=UTC)
        assert sched.is_due(last, now) is True

    def test_is_due_defaults_to_now(self) -> None:
        sched = IntervalSchedule(1)
        past = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert sched.is_due(past) is True

    def test_is_due_tz_naive_now(self) -> None:
        sched = IntervalSchedule(60)
        last = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        now = datetime(2024, 1, 1, 0, 1, 5)  # naive
        assert sched.is_due(last, now) is True

    def test_is_due_tz_naive_last_run(self) -> None:
        sched = IntervalSchedule(60)
        last = datetime(2024, 1, 1, 0, 0, 0)  # naive
        now = datetime(2024, 1, 1, 0, 1, 5, tzinfo=UTC)
        assert sched.is_due(last, now) is True

    def test_repr(self) -> None:
        sched = IntervalSchedule(30)
        assert "30" in repr(sched)
        assert "IntervalSchedule" in repr(sched)


# ---------------------------------------------------------------------------
# CronSchedule — stdlib mode
# ---------------------------------------------------------------------------


class TestCronScheduleStdlib:
    def setup_method(self) -> None:
        # Patch _HAS_CRONITER to False so stdlib fallback is used
        self._patcher = patch("openviper.tasks.schedule._HAS_CRONITER", False)
        self._patcher.start()

    def teardown_method(self) -> None:
        self._patcher.stop()

    def test_parse_valid_expr(self) -> None:
        sched = CronSchedule("* * * * *")
        assert sched._fields is not None
        assert len(sched._fields) == 5

    def test_parse_invalid_fields(self) -> None:
        with pytest.raises(ValueError, match="5-field"):
            CronSchedule("* * *")

    def test_is_due_matches(self) -> None:
        # Use a specific time: minute=0, hour=8, dom=1, month=1, weekday=0 (Monday→cron_dow=1)
        sched = CronSchedule("0 8 1 1 *")
        now = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)  # Monday Jan 1 2024
        assert sched.is_due(None, now) is True

    def test_is_due_no_match(self) -> None:
        sched = CronSchedule("0 8 * * *")
        now = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
        assert sched.is_due(None, now) is False

    def test_is_due_tz_naive_now(self) -> None:
        sched = CronSchedule("* * * * *")
        now = datetime(2024, 1, 1, 8, 0)  # naive
        assert sched.is_due(None, now) is True

    def test_is_due_defaults_to_now(self) -> None:
        sched = CronSchedule("* * * * *")
        # last_run=None → always due
        assert sched.is_due(None) is True

    def test_repr(self) -> None:
        sched = CronSchedule("0 * * * *")
        assert "CronSchedule" in repr(sched)
        assert "0 * * * *" in repr(sched)


# ---------------------------------------------------------------------------
# CronSchedule — croniter mode
# ---------------------------------------------------------------------------


class TestCronScheduleWithCroniter:
    def test_is_due_none_last_run(self) -> None:
        with patch("openviper.tasks.schedule._HAS_CRONITER", True):
            sched = CronSchedule("* * * * *")
            sched._use_croniter = True
            assert sched.is_due(None) is True

    def test_croniter_is_due_past(self) -> None:
        mock_croniter = MagicMock()
        mock_it = MagicMock()
        next_run = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
        mock_it.get_next.return_value = next_run
        mock_croniter.croniter.return_value = mock_it

        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", mock_croniter),
        ):
            sched = CronSchedule("0 8 * * *")
            sched._use_croniter = True
            now = datetime(2024, 1, 1, 8, 5, tzinfo=UTC)
            last = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
            assert sched.is_due(last, now) is True

    def test_croniter_is_due_future(self) -> None:
        mock_croniter = MagicMock()
        mock_it = MagicMock()
        next_run = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        mock_it.get_next.return_value = next_run
        mock_croniter.croniter.return_value = mock_it

        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", mock_croniter),
        ):
            sched = CronSchedule("0 10 * * *")
            sched._use_croniter = True
            now = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
            last = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
            assert sched.is_due(last, now) is False

    def test_croniter_tz_naive_last_run(self) -> None:
        mock_croniter = MagicMock()
        mock_it = MagicMock()
        next_run = datetime(2024, 1, 1, 7, 1, tzinfo=UTC)
        mock_it.get_next.return_value = next_run
        mock_croniter.croniter.return_value = mock_it

        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", mock_croniter),
        ):
            sched = CronSchedule("* * * * *")
            sched._use_croniter = True
            last = datetime(2024, 1, 1, 7, 0)  # naive
            now = datetime(2024, 1, 1, 7, 5, tzinfo=UTC)
            assert sched.is_due(last, now) is True

    def test_croniter_tz_naive_next_run(self) -> None:
        mock_croniter = MagicMock()
        mock_it = MagicMock()
        # next_run without tzinfo
        mock_it.get_next.return_value = datetime(2024, 1, 1, 7, 1)
        mock_croniter.croniter.return_value = mock_it

        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", mock_croniter),
        ):
            sched = CronSchedule("* * * * *")
            sched._use_croniter = True
            last = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
            now = datetime(2024, 1, 1, 7, 5, tzinfo=UTC)
            assert sched.is_due(last, now) is True

    def test_croniter_error_falls_back_to_stdlib(self) -> None:
        mock_croniter = MagicMock()
        mock_croniter.croniter.side_effect = RuntimeError("boom")

        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", mock_croniter),
        ):
            sched = CronSchedule("* * * * *")
            sched._use_croniter = True
            sched._fields = None  # will be lazily parsed
            last = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
            now = datetime(2024, 1, 1, 7, 5, tzinfo=UTC)
            # Should not raise, falls back to stdlib
            result = sched.is_due(last, now)
            assert isinstance(result, bool)

    def test_croniter_not_available_falls_back(self) -> None:
        with (
            patch("openviper.tasks.schedule._HAS_CRONITER", True),
            patch("openviper.tasks.schedule.croniter_lib", None),
        ):
            sched = CronSchedule("* * * * *")
            sched._use_croniter = True
            sched._fields = None
            now = datetime(2024, 1, 1, 7, 5, tzinfo=UTC)
            result = sched.is_due(None, now)
            assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _try_import_croniter
# ---------------------------------------------------------------------------


class TestTryImportCroniter:
    def test_returns_bool(self) -> None:
        result = _try_import_croniter()
        assert isinstance(result, bool)

    def test_returns_true_when_available(self) -> None:
        with patch("openviper.tasks.schedule._HAS_CRONITER", True):
            assert _try_import_croniter() is True

    def test_returns_false_when_unavailable(self) -> None:
        with patch("openviper.tasks.schedule._HAS_CRONITER", False):
            assert _try_import_croniter() is False
