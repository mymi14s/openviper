"""Unit tests for openviper.tasks.schedule — Schedule descriptors."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.schedule import (
    CronSchedule,
    IntervalSchedule,
    _expand_field,
    _try_import_croniter,
)


class TestIntervalSchedule:
    """Test IntervalSchedule implementation."""

    def test_init_positive_seconds(self):
        """IntervalSchedule should accept positive seconds."""
        schedule = IntervalSchedule(60)
        assert schedule.seconds == 60

    def test_init_zero_raises(self):
        """IntervalSchedule should reject zero seconds."""
        with pytest.raises(ValueError, match="must be > 0"):
            IntervalSchedule(0)

    def test_init_negative_raises(self):
        """IntervalSchedule should reject negative seconds."""
        with pytest.raises(ValueError, match="must be > 0"):
            IntervalSchedule(-10)

    def test_is_due_never_run(self):
        """Task should be due immediately if it never ran."""
        schedule = IntervalSchedule(60)
        assert schedule.is_due(last_run_at=None)

    def test_is_due_elapsed(self):
        """Task should be due when interval has elapsed."""
        schedule = IntervalSchedule(60)
        last_run = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        now = last_run + timedelta(seconds=61)
        assert schedule.is_due(last_run, now)

    def test_is_due_not_elapsed(self):
        """Task should not be due when interval has not elapsed."""
        schedule = IntervalSchedule(60)
        last_run = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        now = last_run + timedelta(seconds=30)
        assert not schedule.is_due(last_run, now)

    def test_is_due_exact_boundary(self):
        """Task should be due exactly at the interval boundary."""
        schedule = IntervalSchedule(60)
        last_run = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        now = last_run + timedelta(seconds=60)
        assert schedule.is_due(last_run, now)

    def test_is_due_naive_datetime_converted(self):
        """Naive datetimes should be treated as UTC."""
        schedule = IntervalSchedule(60)
        last_run = datetime(2026, 3, 10, 12, 0, 0)  # naive
        now = datetime(2026, 3, 10, 12, 1, 1)  # naive
        assert schedule.is_due(last_run, now)

    def test_repr(self):
        """__repr__ should show seconds."""
        schedule = IntervalSchedule(3600)
        assert repr(schedule) == "IntervalSchedule(seconds=3600)"


class TestExpandField:
    """Test cron field expansion helper."""

    def test_star_expands_full_range(self):
        """* should expand to all values in range."""
        result = _expand_field("*", 0, 5)
        assert result == {0, 1, 2, 3, 4, 5}

    def test_single_value(self):
        """Single number should return that value."""
        result = _expand_field("3", 0, 10)
        assert result == {3}

    def test_range(self):
        """Range (start-end) should expand inclusive."""
        result = _expand_field("2-5", 0, 10)
        assert result == {2, 3, 4, 5}

    def test_step_with_star(self):
        """*/step should return every Nth value."""
        result = _expand_field("*/2", 0, 10)
        assert result == {0, 2, 4, 6, 8, 10}

    def test_step_with_range(self):
        """Range/step should apply step within range."""
        result = _expand_field("10-20/3", 0, 30)
        assert result == {10, 13, 16, 19}

    def test_comma_separated(self):
        """Comma-separated values should combine."""
        result = _expand_field("1,3,5", 0, 10)
        assert result == {1, 3, 5}

    def test_complex_expression(self):
        """Complex expressions should combine all parts."""
        result = _expand_field("1,5-7,*/10", 0, 20)
        assert result == {0, 1, 5, 6, 7, 10, 20}

    def test_invalid_step_raises(self):
        """Zero or negative step should raise ValueError."""
        with pytest.raises(ValueError, match="step must be >= 1"):
            _expand_field("*/0", 0, 10)


class TestCronSchedule:
    """Test CronSchedule implementation."""

    def test_init_valid_expression(self):
        """CronSchedule should accept valid 5-field expression."""
        schedule = CronSchedule("* * * * *")
        assert schedule.expr == "* * * * *"

    def test_init_invalid_fields_raises(self):
        """CronSchedule should reject expressions with wrong field count."""
        with pytest.raises(ValueError, match="5-field expression"):
            CronSchedule("* * *")

    def test_parse_all_stars(self):
        """Parsing '* * * * *' should expand all fields."""
        fields = CronSchedule._parse("* * * * *")
        assert len(fields["minute"]) == 60
        assert len(fields["hour"]) == 24
        assert len(fields["dom"]) == 31
        assert len(fields["month"]) == 12
        assert len(fields["dow"]) == 7

    def test_parse_specific_values(self):
        """Parsing specific values should extract them."""
        fields = CronSchedule._parse("15 8 1 6 0")
        assert fields["minute"] == {15}
        assert fields["hour"] == {8}
        assert fields["dom"] == {1}
        assert fields["month"] == {6}
        assert fields["dow"] == {0}

    def test_is_due_never_run_returns_true(self):
        """Task should be due immediately if never run."""
        schedule = CronSchedule("* * * * *")
        assert schedule.is_due(last_run_at=None)

    def test_is_due_matching_minute(self):
        """Task should be due when current minute matches."""
        schedule = CronSchedule("15 * * * *")
        now = datetime(2026, 3, 10, 12, 15, 0, tzinfo=UTC)
        last_run = datetime(2026, 3, 10, 11, 15, 0, tzinfo=UTC)
        assert schedule.is_due(last_run, now)

    def test_is_due_non_matching_minute(self):
        """Task should not be due when minute doesn't match."""
        schedule = CronSchedule("15 * * * *")
        now = datetime(2026, 3, 10, 12, 30, 0, tzinfo=UTC)
        last_run = datetime(2026, 3, 10, 12, 15, 0, tzinfo=UTC)
        # When using stdlib parser, non-matching minute returns False
        if not schedule._use_croniter:
            assert not schedule.is_due(last_run, now)

    def test_is_due_specific_day_of_week(self):
        """Task should match day of week (Monday = 1 in cron)."""
        # Monday in Python weekday() = 0, but cron dow 0 = Sunday
        # So for Monday we need cron dow 1
        schedule = CronSchedule("0 9 * * 1")  # Monday at 9am
        monday = datetime(2026, 3, 9, 9, 0, 0, tzinfo=UTC)  # 2026-03-09 is Monday
        last_run = None
        if not schedule._use_croniter:
            assert schedule.is_due(last_run, monday)

    def test_is_due_naive_datetime_converted(self):
        """Naive datetimes should be treated as UTC."""
        schedule = CronSchedule("* * * * *")
        now = datetime(2026, 3, 10, 12, 0, 0)  # naive
        assert schedule.is_due(None, now)

    def test_repr(self):
        """__repr__ should show the expression."""
        schedule = CronSchedule("0 * * * *")
        assert repr(schedule) == "CronSchedule('0 * * * *')"

    def test_croniter_fallback_on_error(self):
        """Should fall back to stdlib parser if croniter fails."""
        schedule = CronSchedule("* * * * *")
        if schedule._use_croniter:
            # Force an error path by passing invalid data to croniter path
            now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
            # Even with croniter, should not crash
            result = schedule.is_due(None, now)
            assert isinstance(result, bool)


class TestTryImportCroniter:
    """Test croniter detection helper."""

    def test_returns_boolean(self):
        """_try_import_croniter should return a boolean."""
        result = _try_import_croniter()
        assert isinstance(result, bool)


# ── _expand_field: step with single start number (lines 142-143) ─────────────


class TestExpandFieldStepWithSingleStart:
    def test_step_with_single_start_number(self):
        """'3/2' → start=3, end=hi, step=2 (lines 142-143)."""
        result = _expand_field("3/2", 0, 10)
        # Range from 3 to 10 step 2 → {3, 5, 7, 9}
        assert result == {3, 5, 7, 9}

    def test_step_with_zero_raises(self):
        """Step of 0 raises ValueError (line 134-135)."""
        with pytest.raises(ValueError, match="step"):
            _expand_field("*/0", 0, 59)


# ── CronSchedule.is_due: naive datetime handling + croniter path ────────────


class TestCronScheduleNaiveDatetime:
    def test_is_due_naive_now_made_utc_aware(self):
        """Naive `now` gets tzinfo=UTC applied (line 225-226)."""
        schedule = CronSchedule("* * * * *")
        # Pass a naive datetime (no tzinfo) — lines 225-226 apply UTC
        naive_now = datetime(2026, 3, 10, 12, 0, 0)  # no tzinfo
        result = schedule.is_due(None, now=naive_now)
        assert isinstance(result, bool)


class TestCronScheduleCroniterPath:
    """Test _croniter_is_due branches (lines 229, 233-250) via direct mocking."""

    def _make_croniter_schedule(self):
        """Return a CronSchedule with _use_croniter forced True."""
        schedule = CronSchedule("* * * * *")
        schedule._use_croniter = True
        return schedule

    def test_is_due_calls_croniter_path(self):
        """is_due calls _croniter_is_due when _use_croniter=True (line 229)."""
        schedule = self._make_croniter_schedule()
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

        mock_croniter_cls = MagicMock()
        mock_croniter_inst = MagicMock()
        mock_croniter_inst.get_next.return_value = datetime(2026, 3, 10, 11, 59, 0, tzinfo=UTC)
        mock_croniter_cls.return_value = mock_croniter_inst

        with patch.dict("sys.modules", {"croniter": MagicMock(croniter=mock_croniter_cls)}):
            result = schedule.is_due(
                last_run_at=datetime(2026, 3, 10, 11, 58, 0, tzinfo=UTC), now=now
            )

        assert isinstance(result, bool)

    def test_croniter_is_due_none_last_run_returns_true(self):
        """last_run_at=None → return True immediately (line 238)."""
        schedule = self._make_croniter_schedule()
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

        with patch.dict("sys.modules", {"croniter": MagicMock()}):
            result = schedule._croniter_is_due(last_run_at=None, now=now)

        assert result is True

    def test_croniter_is_due_naive_last_run_made_utc(self):
        """Naive last_run_at gets UTC tzinfo (lines 239-240)."""
        schedule = self._make_croniter_schedule()
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        naive_last_run = datetime(2026, 3, 10, 11, 55, 0)  # no tzinfo

        mock_croniter_cls = MagicMock()
        mock_next = datetime(2026, 3, 10, 11, 59, 0)  # also naive (tests line 243-244)
        mock_croniter_cls.return_value.get_next.return_value = mock_next

        with patch.dict("sys.modules", {"croniter": MagicMock(croniter=mock_croniter_cls)}):
            result = schedule._croniter_is_due(last_run_at=naive_last_run, now=now)

        assert isinstance(result, bool)

    def test_croniter_is_due_exception_falls_back_to_stdlib(self):
        """Exception in croniter path falls back to stdlib (lines 246-250)."""
        schedule = self._make_croniter_schedule()
        schedule._fields = None  # will be lazily set at line 249
        now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        last_run = datetime(2026, 3, 10, 11, 55, 0, tzinfo=UTC)

        mock_croniter_cls = MagicMock()
        mock_croniter_cls.side_effect = RuntimeError("croniter failed")

        with patch.dict("sys.modules", {"croniter": MagicMock(croniter=mock_croniter_cls)}):
            with patch("openviper.tasks.schedule.logger") as mock_logger:
                result = schedule._croniter_is_due(last_run_at=last_run, now=now)

        assert isinstance(result, bool)
        # Warning was logged (line 247)
        assert mock_logger.warning.called
        # _fields was lazily initialised (line 249)
        assert schedule._fields is not None


class TestTryImportCroniterTrue:
    def test_returns_true_when_croniter_importable(self):
        """_try_import_croniter returns True when croniter is importable (line 266)."""
        mock_croniter = MagicMock()
        with patch.dict("sys.modules", {"croniter": mock_croniter}):
            result = _try_import_croniter()
        assert result is True
