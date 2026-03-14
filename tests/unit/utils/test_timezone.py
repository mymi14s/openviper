"""Unit tests for openviper.utils.timezone."""

import datetime
import zoneinfo
from unittest.mock import patch

import pytest

from openviper.utils.timezone import (
    get_current_timezone,
    is_aware,
    is_naive,
    make_aware,
    make_naive,
    now,
)


class TestTimezoneIsAwareNaive:
    def test_is_aware(self):
        aware_dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        assert is_aware(aware_dt) is True

    def test_is_naive(self):
        naive_dt = datetime.datetime(2024, 1, 1)
        assert is_naive(naive_dt) is True

    def test_aware_is_not_naive(self):
        aware_dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        assert is_aware(aware_dt) is True
        assert is_naive(aware_dt) is False


class TestMakeAware:
    def test_makes_naive_aware(self):

        naive = datetime.datetime(2024, 1, 1)
        tz = zoneinfo.ZoneInfo("UTC")
        aware = make_aware(naive, tz)
        assert aware.tzinfo == tz

    def test_raises_on_already_aware(self):

        aware = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        with pytest.raises(ValueError, match="make_aware"):
            make_aware(aware, zoneinfo.ZoneInfo("UTC"))


class TestMakeNaive:
    def test_makes_aware_naive(self):

        aware = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        naive = make_naive(aware, zoneinfo.ZoneInfo("UTC"))
        assert naive.tzinfo is None

    def test_raises_on_already_naive(self):

        naive = datetime.datetime(2024, 1, 1)
        with pytest.raises(ValueError, match="make_naive"):
            make_naive(naive, zoneinfo.ZoneInfo("UTC"))


class TestNow:
    def test_now_with_tz(self):

        with patch("openviper.utils.timezone.settings") as mock_settings:
            mock_settings.USE_TZ = True
            result = now()
        assert result.tzinfo is not None

    def test_now_without_tz(self):

        with patch("openviper.utils.timezone.settings") as mock_settings:
            mock_settings.USE_TZ = False
            result = now()
        assert result.tzinfo is None


class TestGetCurrentTimezone:
    def test_returns_zoneinfo(self):
        """L13: get_current_timezone returns ZoneInfo for settings.TIME_ZONE."""

        tz = get_current_timezone()
        assert isinstance(tz, datetime.tzinfo)


class TestMakeAwareDefaultTz:
    def test_make_aware_no_tz_arg(self):
        """L42: make_aware with no explicit timezone uses get_current_timezone."""

        naive = datetime.datetime(2024, 6, 15, 12, 0, 0)
        aware = make_aware(naive)
        assert aware.tzinfo is not None


class TestMakeNaiveDefaultTz:
    def test_make_naive_no_tz_arg(self):
        """L55: make_naive with no explicit timezone uses get_current_timezone."""

        aware = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        naive = make_naive(aware)
        assert naive.tzinfo is None
