"""Timezone utilities for aware and naive datetime handling."""

from __future__ import annotations

import datetime
import zoneinfo

from openviper.conf import settings

__all__ = [
    "utc",
    "get_current_timezone",
    "now",
    "is_aware",
    "is_naive",
    "make_aware",
    "make_naive",
    "localtime",
]

utc: datetime.timezone = datetime.UTC


def _get_settings() -> object:
    """Return settings through a helper for backwards-compatible patching."""
    return settings


def get_current_timezone() -> zoneinfo.ZoneInfo:
    """Return a ZoneInfo instance for the configured TIME_ZONE."""
    return zoneinfo.ZoneInfo(_get_settings().TIME_ZONE)


def now() -> datetime.datetime:
    """Return the current time.

    If USE_TZ is True, returns an aware UTC datetime.
    Otherwise, returns a naive local datetime.
    """
    if _get_settings().USE_TZ:
        return datetime.datetime.now(datetime.UTC)
    return datetime.datetime.now()


def is_aware(value: datetime.datetime) -> bool:
    """Determine if a given datetime object is aware."""
    return value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None


def is_naive(value: datetime.datetime) -> bool:
    """Determine if a given datetime object is naive."""
    return value.tzinfo is None or value.tzinfo.utcoffset(value) is None


def make_aware(
    value: datetime.datetime, timezone: zoneinfo.ZoneInfo | None = None
) -> datetime.datetime:
    """Make a naive datetime aware in a specific timezone."""
    if timezone is None:
        timezone = get_current_timezone()

    if is_aware(value):
        raise ValueError(f"make_aware expects a naive datetime, got {value}")

    return value.replace(tzinfo=timezone)


def make_naive(
    value: datetime.datetime, timezone: zoneinfo.ZoneInfo | None = None
) -> datetime.datetime:
    """Make an aware datetime naive in a specific timezone."""
    if timezone is None:
        timezone = get_current_timezone()

    if is_naive(value):
        raise ValueError(f"make_naive expects an aware datetime, got {value}")

    return value.astimezone(timezone).replace(tzinfo=None)


def localtime(
    value: datetime.datetime | None = None, timezone: zoneinfo.ZoneInfo | None = None
) -> datetime.datetime:
    """Convert an aware datetime to the configured timezone.

    If *value* is ``None``, returns the current time in the configured timezone.
    If *value* is naive, it is assumed to be in the configured timezone.
    """
    tz = timezone or get_current_timezone()
    if value is None:
        return datetime.datetime.now(tz)
    if is_aware(value):
        return value.astimezone(tz)
    return make_aware(value, tz)
