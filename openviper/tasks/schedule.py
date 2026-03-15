"""Schedule descriptors for OpenViper's periodic task system.

Two concrete schedule types are provided:

* :class:`CronSchedule` — parses a five-field cron expression
  (``"*/5 * * * *"``).  Uses ``croniter`` when installed; falls back to a
  minimal built-in evaluator for simple patterns.
* :class:`IntervalSchedule` — fires every *N* seconds.

Both implement the :class:`Schedule` protocol so that the scheduler loop can
call ``schedule.is_due(last_run_at, now)`` uniformly.

Usage::

    from openviper.tasks.schedule import CronSchedule, IntervalSchedule

    every_minute = CronSchedule("* * * * *")
    every_5s     = IntervalSchedule(5)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import cast

logger = logging.getLogger("openviper.tasks")

__all__ = [
    "Schedule",
    "CronSchedule",
    "IntervalSchedule",
]


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class Schedule(ABC):
    """Protocol / abstract base class for all schedule descriptors."""

    @abstractmethod
    def is_due(self, last_run_at: datetime | None, now: datetime | None = None) -> bool:
        """Return ``True`` if the task should be enqueued right now.

        Args:
            last_run_at: The UTC datetime of the most recent successful
                         enqueue, or ``None`` if the task has never run.
            now:         The current UTC datetime.  Defaults to
                         ``datetime.now(timezone.utc)`` when ``None``.
        """

    @abstractmethod
    def __repr__(self) -> str:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# IntervalSchedule
# ---------------------------------------------------------------------------


class IntervalSchedule(Schedule):
    """Fire every *seconds* seconds.

    Args:
        seconds: Minimum number of seconds between consecutive enqueues.
                 Must be a positive number.

    Raises:
        ValueError: If *seconds* is not positive.

    Example::

        IntervalSchedule(60)    # every minute
        IntervalSchedule(3600)  # every hour
    """

    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError(f"IntervalSchedule seconds must be > 0, got {seconds!r}")
        self.seconds = seconds

    def is_due(self, last_run_at: datetime | None, now: datetime | None = None) -> bool:
        """Return ``True`` when at least *seconds* have elapsed since *last_run_at*."""
        if last_run_at is None:
            return True
        _now = now if now is not None else datetime.now(UTC)
        # Ensure both datetimes are timezone-aware before subtracting.
        if _now.tzinfo is None:
            _now = _now.replace(tzinfo=UTC)
        if last_run_at.tzinfo is None:
            last_run_at = last_run_at.replace(tzinfo=UTC)
        elapsed = (_now - last_run_at).total_seconds()
        return elapsed >= self.seconds

    def __repr__(self) -> str:
        return f"IntervalSchedule(seconds={self.seconds!r})"


# ---------------------------------------------------------------------------
# CronSchedule
# ---------------------------------------------------------------------------

# Field order: minute, hour, day-of-month, month, day-of-week
_CRON_FIELD_NAMES = ("minute", "hour", "dom", "month", "dow")
_CRON_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dom": (1, 31),
    "month": (1, 12),
    "dow": (0, 6),
}


def _expand_field(token: str, lo: int, hi: int) -> set[int]:
    """Expand a single cron field token into a set of integers.

    Supported sub-expressions: ``*``, ``*/step``, ``value``, ``start-end``,
    ``start-end/step``, and comma-separated combinations.

    Raises:
        ValueError: On unparseable tokens.
    """
    result: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if "/" in part:
            range_part, step_str = part.rsplit("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Cron step must be >= 1, got {step!r}")
            if range_part == "*":
                start, end = lo, hi
            elif "-" in range_part:
                s, e = range_part.split("-", 1)
                start, end = int(s), int(e)
            else:
                start = int(range_part)
                end = hi
            result.update(range(start, end + 1, step))
        elif part == "*":
            result.update(range(lo, hi + 1))
        elif "-" in part:
            s, e = part.split("-", 1)
            result.update(range(int(s), int(e) + 1))
        else:
            result.add(int(part))
    return result


class CronSchedule(Schedule):
    """Fire according to a standard five-field cron expression.

    Attempts to use ``croniter`` (``pip install croniter``) for full cron
    semantics including special strings like ``@hourly``.  Falls back to a
    built-in evaluator for simpler patterns when ``croniter`` is not installed.

    Args:
        expr:       Five-field cron expression, e.g. ``"*/5 * * * *"``.
        use_seconds: Reserved; currently ignored (minute-granularity only).

    Raises:
        ValueError: If *expr* cannot be parsed.

    Example::

        CronSchedule("0 * * * *")     # top of every hour
        CronSchedule("*/15 * * * *")  # every 15 minutes
    """

    def __init__(self, expr: str, *, use_seconds: bool = False) -> None:
        self.expr = expr.strip()
        self._use_croniter = _try_import_croniter()
        self._fields: dict[str, set[int]] | None = None
        if not self._use_croniter:
            self._fields = self._parse(self.expr)

    # ------------------------------------------------------------------
    # Internal parsing (stdlib-only fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(expr: str) -> dict[str, set[int]]:
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"CronSchedule expects a 5-field expression, got {len(parts)} fields: {expr!r}"
            )
        return {
            name: _expand_field(token, *_CRON_FIELD_RANGES[name])
            for name, token in zip(_CRON_FIELD_NAMES, parts, strict=False)
        }

    def _stdlib_is_due(self, last_run_at: datetime | None, now: datetime) -> bool:
        """Check whether *now* matches the cron expression (minute granularity)."""
        assert self._fields is not None  # nosec B101
        # Cron dow uses 0=Sunday…6=Saturday; Python weekday() uses 0=Monday…6=Sunday.
        # Convert: cron_dow = (python_weekday + 1) % 7
        cron_dow = (now.weekday() + 1) % 7
        return (
            now.minute in self._fields["minute"]
            and now.hour in self._fields["hour"]
            and now.day in self._fields["dom"]
            and now.month in self._fields["month"]
            and cron_dow in self._fields["dow"]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_due(self, last_run_at: datetime | None, now: datetime | None = None) -> bool:
        """Return ``True`` if the cron expression matches the current minute.

        Uses ``croniter`` when available; otherwise falls back to the built-in
        evaluator.  Note: this checks whether *now* falls within the cron
        period — call ``tick()`` at most once per minute to avoid duplicate
        enqueues.
        """
        _now = now if now is not None else datetime.now(UTC)
        if _now.tzinfo is None:
            _now = _now.replace(tzinfo=UTC)

        if self._use_croniter:
            return self._croniter_is_due(last_run_at, _now)
        return self._stdlib_is_due(last_run_at, _now)

    def _croniter_is_due(self, last_run_at: datetime | None, now: datetime) -> bool:
        try:
            from croniter import croniter  # type: ignore[import-untyped]

            if last_run_at is None:
                # Never run — treat as due immediately.
                return True
            if last_run_at.tzinfo is None:
                last_run_at = last_run_at.replace(tzinfo=UTC)
            it = croniter(self.expr, last_run_at)
            next_run = it.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=UTC)
            return cast("bool", now >= next_run)
        except Exception as exc:
            logger.warning("croniter error for %r: %s — falling back to stdlib", self.expr, exc)
            if self._fields is None:
                self._fields = self._parse(self.expr)
            return self._stdlib_is_due(last_run_at, now)

    def __repr__(self) -> str:
        return f"CronSchedule({self.expr!r})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import_croniter() -> bool:
    """Return ``True`` if ``croniter`` is importable."""
    try:
        import croniter  # noqa: F401

        return True
    except ImportError:
        return False
