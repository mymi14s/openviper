"""Integration tests for openviper.utils.timezone."""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# get_current_timezone
# ---------------------------------------------------------------------------


def test_get_current_timezone_returns_zone_info():
    tz = get_current_timezone()
    assert isinstance(tz, zoneinfo.ZoneInfo)


def test_get_current_timezone_uses_settings():
    with patch("openviper.utils.timezone.settings") as ms:
        ms.TIME_ZONE = "America/New_York"
        tz = get_current_timezone()
    assert str(tz) == "America/New_York"


# ---------------------------------------------------------------------------
# now()
# ---------------------------------------------------------------------------


def test_now_use_tz_true_returns_aware():
    with patch("openviper.utils.timezone.settings") as ms:
        ms.USE_TZ = True
        result = now()
    assert result.tzinfo is not None


def test_now_use_tz_false_returns_naive():
    with patch("openviper.utils.timezone.settings") as ms:
        ms.USE_TZ = False
        result = now()
    # naive datetimes have no tzinfo (or offset is None)
    assert is_naive(result)


# ---------------------------------------------------------------------------
# is_aware / is_naive
# ---------------------------------------------------------------------------


def test_is_aware_with_aware_datetime():
    dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    assert is_aware(dt) is True
    assert is_naive(dt) is False


def test_is_naive_with_naive_datetime():
    dt = datetime.datetime(2024, 1, 1)
    assert is_naive(dt) is True
    assert is_aware(dt) is False


# ---------------------------------------------------------------------------
# make_aware
# ---------------------------------------------------------------------------


def test_make_aware_attaches_timezone():
    naive = datetime.datetime(2024, 6, 15, 12, 0, 0)
    tz = zoneinfo.ZoneInfo("UTC")
    result = make_aware(naive, tz)
    assert result.tzinfo is not None


def test_make_aware_uses_default_tz_when_none():
    naive = datetime.datetime(2024, 6, 15, 12, 0, 0)
    with patch("openviper.utils.timezone.settings") as ms:
        ms.TIME_ZONE = "UTC"
        result = make_aware(naive)
    assert result.tzinfo is not None


def test_make_aware_raises_if_already_aware():
    aware = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    with pytest.raises(ValueError, match="make_aware expects a naive datetime"):
        make_aware(aware)


# ---------------------------------------------------------------------------
# make_naive
# ---------------------------------------------------------------------------


def test_make_naive_strips_timezone():
    aware = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    tz = zoneinfo.ZoneInfo("UTC")
    result = make_naive(aware, tz)
    assert result.tzinfo is None


def test_make_naive_uses_default_tz_when_none():
    aware = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    with patch("openviper.utils.timezone.settings") as ms:
        ms.TIME_ZONE = "UTC"
        result = make_naive(aware)
    assert result.tzinfo is None


def test_make_naive_raises_if_already_naive():
    naive = datetime.datetime(2024, 1, 1)
    with pytest.raises(ValueError, match="make_naive expects an aware datetime"):
        make_naive(naive)
