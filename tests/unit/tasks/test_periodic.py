"""Tests for openviper.tasks.periodic - periodic decorator and interval parser."""

from __future__ import annotations

import pytest

from openviper.tasks.periodic import parse_interval, periodic
from openviper.tasks.registry import Registry


class TestParseInterval:
    """Test the interval string parser."""

    def test_seconds(self) -> None:
        assert parse_interval("30s") == 30

    def test_minutes(self) -> None:
        assert parse_interval("5m") == 300

    def test_hours(self) -> None:
        assert parse_interval("1h") == 3600

    def test_days(self) -> None:
        assert parse_interval("7d") == 604800

    def test_whitespace_stripped(self) -> None:
        assert parse_interval(" 5m ") == 300

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("5x")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("")

    def test_zero_value(self) -> None:
        assert parse_interval("0s") == 0


class TestPeriodicDecorator:
    """Test the @periodic decorator."""

    def setup_method(self) -> None:
        Registry().clear()

    def test_periodic_with_every(self) -> None:
        @periodic(every="60s")
        async def health_check_periodic() -> None:
            pass

        registry = Registry()
        assert health_check_periodic.__qualname__ in registry.periodic_jobs

    def test_periodic_with_cron(self) -> None:
        @periodic(cron="0 8 * * *")
        async def morning_report_periodic() -> None:
            pass

        registry = Registry()
        assert morning_report_periodic.__qualname__ in registry.periodic_jobs

    def test_periodic_requires_cron_or_every(self) -> None:
        with pytest.raises(ValueError, match="requires either"):

            @periodic()
            async def no_schedule() -> None:
                pass

    def test_periodic_rejects_both_cron_and_every(self) -> None:
        with pytest.raises(ValueError, match="not both"):

            @periodic(cron="* * * * *", every="60s")
            async def both_schedules() -> None:
                pass

    def test_periodic_config_in_registry(self) -> None:
        @periodic(every="5m", startup=True)
        async def config_task() -> None:
            pass

        registry = Registry()
        entry = registry.periodic_jobs[config_task.__qualname__]
        assert entry["startup"] is True

    def test_periodic_cron_stores_schedule(self) -> None:
        """Cron expressions should be stored in the periodic registry."""

        @periodic(cron="0 8 * * *")
        async def cron_task() -> None:
            pass

        registry = Registry()
        entry = registry.periodic_jobs[cron_task.__qualname__]
        assert entry["cron"] == "0 8 * * *"

    def test_periodic_every_stores_interval(self) -> None:
        """Interval schedules should store the every value in the registry."""

        @periodic(every="5m")
        async def interval_task() -> None:
            pass

        registry = Registry()
        entry = registry.periodic_jobs[interval_task.__qualname__]
        assert entry["every"] == "5m"

    def test_periodic_dedup_is_automatic(self) -> None:
        """Deduplication is automatic - no singleton flag needed."""

        @periodic(every="1h")
        async def auto_dedup_task() -> None:
            pass

        registry = Registry()
        entry = registry.periodic_jobs[auto_dedup_task.__qualname__]
        assert "singleton" not in entry

    def test_duplicate_periodic_name_raises(self) -> None:
        @periodic(every="60s")
        async def dup_first() -> None:
            pass

        with pytest.raises(ValueError, match="already registered"):

            @periodic(every="60s")
            async def dup_first() -> None:  # noqa: F811
                pass
