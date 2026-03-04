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


def test_get_current_timezone():
    with patch("openviper.utils.timezone.settings") as mock_settings:
        mock_settings.TIME_ZONE = "America/New_York"
        tz = get_current_timezone()
        assert isinstance(tz, zoneinfo.ZoneInfo)
        assert tz.key == "America/New_York"


def test_now():
    with patch("openviper.utils.timezone.settings") as mock_settings:
        mock_settings.USE_TZ = True
        dt = now()
        assert is_aware(dt)
        assert dt.tzinfo == datetime.UTC

        mock_settings.USE_TZ = False
        dt_naive = now()
        assert is_naive(dt_naive)


def test_is_aware_and_naive():
    naive = datetime.datetime(2023, 1, 1, 12, 0)
    aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.UTC)

    # Fake tzinfo with no offset
    class BadTz(datetime.tzinfo):
        def utcoffset(self, dt):
            return None

    bad_aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=BadTz())

    assert is_naive(naive)
    assert not is_aware(naive)

    assert is_aware(aware)
    assert not is_naive(aware)

    assert is_naive(bad_aware)
    assert not is_aware(bad_aware)


def test_make_aware():
    naive = datetime.datetime(2023, 1, 1, 12, 0)
    aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.UTC)
    tz = zoneinfo.ZoneInfo("America/New_York")

    res = make_aware(naive, tz)
    assert is_aware(res)
    assert res.tzinfo == tz

    with pytest.raises(ValueError, match="make_aware expects a naive datetime"):
        make_aware(aware, tz)

    with patch("openviper.utils.timezone.get_current_timezone", return_value=datetime.UTC):
        res_default = make_aware(naive)
        assert res_default.tzinfo == datetime.UTC


def test_make_naive():
    naive = datetime.datetime(2023, 1, 1, 12, 0)
    aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.UTC)
    tz = zoneinfo.ZoneInfo("America/New_York")

    res = make_naive(aware, tz)
    assert is_naive(res)

    with pytest.raises(ValueError, match="make_naive expects an aware datetime"):
        make_naive(naive, tz)

    with patch("openviper.utils.timezone.get_current_timezone", return_value=tz):
        res_default = make_naive(aware)
        assert is_naive(res_default)
