"""Schedule entry registry for OpenViper's periodic task scheduler.

Each registered task is stored as a :class:`ScheduleEntry`.  The
:class:`ScheduleRegistry` singleton keeps track of all entries and answers
``which entries are due right now?``

Usage::

    from openviper.tasks.registry import get_registry

    registry = get_registry()
    registry.register(
        name="send_digest",
        actor=send_digest_actor,
        schedule=CronSchedule("0 8 * * *"),
    )
    due = registry.all_due(now=datetime.now(timezone.utc))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openviper.tasks.schedule import Schedule

logger = logging.getLogger("openviper.tasks")

__all__ = [
    "ScheduleEntry",
    "ScheduleRegistry",
    "get_registry",
]


# ---------------------------------------------------------------------------
# ScheduleEntry
# ---------------------------------------------------------------------------


@dataclass
class ScheduleEntry:
    """Holds all state for one scheduled task."""

    #: Unique human-readable identifier.
    name: str
    #: The Dramatiq actor (registered via ``@task``).
    actor: Any
    #: A :class:`~openviper.tasks.schedule.Schedule` instance.
    schedule: Schedule
    #: Positional arguments forwarded to ``actor.send()``.
    args: tuple[Any, ...] = field(default_factory=tuple)
    #: Keyword arguments forwarded to ``actor.send()``.
    kwargs: dict[str, Any] = field(default_factory=dict)
    #: When ``False`` the entry is never enqueued.
    enabled: bool = True
    #: UTC datetime of the most recent enqueue; ``None`` initially.
    last_run_at: datetime | None = None

    def is_due(self, now: datetime | None = None) -> bool:
        """Delegate to ``self.schedule.is_due`` if the entry is enabled."""
        if not self.enabled:
            return False
        _now = now if now is not None else datetime.now(timezone.utc)
        return self.schedule.is_due(self.last_run_at, _now)


# ---------------------------------------------------------------------------
# ScheduleRegistry
# ---------------------------------------------------------------------------


class ScheduleRegistry:
    """In-process store of :class:`ScheduleEntry` objects.

    Use :func:`get_registry` to obtain the process-level singleton.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ScheduleEntry] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        actor: Any,
        schedule: Schedule,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        enabled: bool = True,
        replace: bool = False,
    ) -> ScheduleEntry:
        """Add a new :class:`ScheduleEntry` to the registry.

        Args:
            name:     Unique identifier.  A second call with the same *name*
                      raises :class:`ValueError` unless *replace* is ``True``.
            actor:    Dramatiq actor to enqueue.
            schedule: Schedule descriptor.
            args:     Positional arguments for the actor.
            kwargs:   Keyword arguments for the actor.
            enabled:  Whether the entry participates in scheduling.
            replace:  If ``True``, silently overwrite an existing entry with
                      the same *name* instead of raising.

        Returns:
            The newly created :class:`ScheduleEntry`.

        Raises:
            ValueError: If *name* is already registered and *replace* is
                        ``False``.
        """
        if name in self._entries and not replace:
            raise ValueError(
                f"A schedule entry named {name!r} already exists.  "
                "Pass replace=True to overwrite it."
            )
        entry = ScheduleEntry(
            name=name,
            actor=actor,
            schedule=schedule,
            args=tuple(args),
            kwargs=dict(kwargs or {}),
            enabled=enabled,
        )
        self._entries[name] = entry
        logger.debug("Registered schedule entry %r (%s)", name, schedule)
        return entry

    def unregister(self, name: str) -> None:
        """Remove the entry named *name*.  No-op if not found."""
        self._entries.pop(name, None)
        logger.debug("Unregistered schedule entry %r", name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, name: str) -> ScheduleEntry | None:
        """Return the entry with *name*, or ``None``."""
        return self._entries.get(name)

    def all_entries(self) -> list[ScheduleEntry]:
        """Return all registered entries."""
        return list(self._entries.values())

    def all_due(self, now: datetime | None = None) -> list[ScheduleEntry]:
        """Return entries whose schedule is currently due.

        Args:
            now: The reference datetime (UTC).  Defaults to
                 ``datetime.now(timezone.utc)``.
        """
        _now = now if now is not None else datetime.now(timezone.utc)
        return [e for e in self._entries.values() if e.is_due(_now)]

    def clear(self) -> None:
        """Remove all entries.  Primarily for tests."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return name in self._entries


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_registry: ScheduleRegistry | None = None


def get_registry() -> ScheduleRegistry:
    """Return the process-level :class:`ScheduleRegistry` singleton."""
    global _registry
    if _registry is None:
        _registry = ScheduleRegistry()
    return _registry


def reset_registry() -> None:
    """Replace the singleton with a fresh registry.  Primarily for tests."""
    global _registry
    _registry = None
