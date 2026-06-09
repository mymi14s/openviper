"""Periodic task decorator and interval parser.

Schedules are expressed as 5-field crontab strings or interval notation
(``30s``, ``5m``, ``1h``, ``7d``). Deduplication across workers
is automatic via database-level locking.
"""

from __future__ import annotations

import re
import typing as t

from openviper.tasks.registry import Registry

INTERVAL_RE = re.compile(
    r"^(?P<value>\d+)\s*(?P<unit>[smhd])$",
    re.IGNORECASE,
)

UNIT_SECONDS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def parse_interval(every: str | int) -> int:
    """Parse an interval string (``30s``, ``5m``, ``1h``, ``7d``) into seconds.

    Plain integers are treated as seconds. Raises :class:`ValueError`
    for unrecognised formats.
    """
    if isinstance(every, int):
        return every
    match = INTERVAL_RE.match(every.strip())
    if not match:
        raise ValueError(f"Invalid interval '{every}'. Use format like '30s', '5m', '1h', '7d'.")
    value = int(match.group("value"))
    unit = match.group("unit").lower()
    return value * UNIT_SECONDS[unit]


def periodic(
    *,
    cron: str | None = None,
    every: str | int | None = None,
    startup: bool = False,
    retries: int = 3,
) -> t.Callable[..., t.Any]:
    """Decorator that registers a callable as a periodic task.

    Exactly one of *cron* or *every* must be provided. Deduplication
    across workers is automatic.

    Args:
        cron: 5-field crontab expression (``"*/5 * * * *"``).
        every: Interval string (``"5m"``) or integer seconds (``60``).
        startup: Run once immediately on worker start.
        retries: Maximum retry attempts on failure.
    """
    if cron is None and every is None:
        raise ValueError("periodic() requires either 'cron' or 'every'")
    if cron is not None and every is not None:
        raise ValueError("periodic() accepts either 'cron' or 'every', not both")

    schedule = cron if cron is not None else str(parse_interval(every))  # type: ignore[arg-type]

    def decorator(fn: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        name = fn.__qualname__
        module = fn.__module__ or ""
        app_label = module.split(".")[0] if module else ""
        registry = Registry()
        registry.register_periodic(
            name,
            schedule=schedule,
            cron=cron,
            every=every,
            startup=startup,
            retries=retries,
            app_label=app_label,
        )

        registry.register_actor(name, fn)

        fn.periodic_config = {
            "name": name,
            "cron": cron,
            "every": every,
            "startup": startup,
            "retries": retries,
        }
        return fn

    return decorator
