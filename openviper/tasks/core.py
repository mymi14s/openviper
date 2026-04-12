"""Core Scheduler class for OpenViper's periodic task system.

:class:`Scheduler` is the entry point for application code.  Register tasks
with :meth:`add` for periodic execution, or call :meth:`run_now` to enqueue
a task immediately without any schedule.

Examples::

    from openviper.tasks.core import Scheduler
    from openviper.tasks.schedule import CronSchedule, IntervalSchedule

    scheduler = Scheduler()

    # Periodic task with arguments
    @task(queue_name="default")
    async def send_report(user_id: int, fmt: str = "pdf") -> None: ...

    scheduler.add(
        "weekly_report",
        send_report,
        CronSchedule("0 8 * * 1"),   # every Monday 08:00
        args=(42,),
        kwargs={"fmt": "csv"},
    )

    # One-shot instant job — enqueue right now, no schedule
    scheduler.run_now(send_report, 42, fmt="html")

    # Periodic loop:
    enqueued = scheduler.tick()   # returns list of names that were sent
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from openviper.tasks.registry import ScheduleEntry, ScheduleRegistry, get_registry

if TYPE_CHECKING:
    from openviper.tasks.schedule import Schedule

logger = logging.getLogger("openviper.tasks")

__all__ = ["Scheduler"]


class Scheduler:
    """Periodic task scheduler backed by a :class:`~openviper.tasks.registry.ScheduleRegistry`.

    Args:
        registry: A custom registry instance.  Uses the process-level
                  singleton when ``None`` (the default).
    """

    def __init__(self, registry: ScheduleRegistry | None = None) -> None:
        self._registry: ScheduleRegistry = registry if registry is not None else get_registry()

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def add(
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
        """Register a new periodic task.

        Args:
            name:     Unique name for the scheduled entry.
            actor:    A Dramatiq actor (decorated with ``@task``).
            schedule: When to enqueue — :class:`CronSchedule` or
                      :class:`IntervalSchedule`.
            args:     Positional args forwarded to ``actor.send()``.
            kwargs:   Keyword args forwarded to ``actor.send()``.
            enabled:  Set to ``False`` to register but suppress enqueuing.
            replace:  Overwrite an existing entry with the same *name*.

        Returns:
            The newly created :class:`~openviper.tasks.registry.ScheduleEntry`.
        """
        return self._registry.register(
            name=name,
            actor=actor,
            schedule=schedule,
            args=args,
            kwargs=kwargs,
            enabled=enabled,
            replace=replace,
        )

    def remove(self, name: str) -> None:
        """Unregister the entry named *name*.  No-op if not found."""
        self._registry.unregister(name)

    # ------------------------------------------------------------------
    # Instant jobs
    # ------------------------------------------------------------------

    def run_now(self, actor: Any, /, *args: Any, **kwargs: Any) -> None:
        """Enqueue *actor* immediately — a one-shot fire-and-forget job.

        Unlike :meth:`add`, this does **not** register a recurring entry in
        the registry.  The message is sent to the Dramatiq broker right away
        and result tracking is handled by the existing
        :class:`~openviper.tasks.middleware.TaskTrackingMiddleware`.

        Args:
            actor:    A Dramatiq actor (decorated with ``@task``).
            *args:    Positional arguments forwarded to ``actor.send()``.
            **kwargs: Keyword arguments forwarded to ``actor.send()``.

        Raises:
            Exception: Re-raises any broker error so the caller can handle it.

        Example::

            scheduler.run_now(send_report, user_id=42, fmt="pdf")
        """
        if not hasattr(actor, "send"):
            raise TypeError(
                f"{actor!r} is a plain function, not a Dramatiq actor.  "
                "Decorate it with @task first:\n\n"
                "    from openviper.tasks import task\n\n"
                "    @task()\n"
                f"    def {getattr(actor, '__name__', 'my_func')}(...):\n"
                "        ...\n\n"
                "Then pass the decorated name to run_now()."
            )
        logger.debug(
            "Instant enqueue: actor=%r  args=%r  kwargs=%r",
            getattr(actor, "actor_name", repr(actor)),
            args,
            kwargs,
        )
        actor.send(*args, **kwargs)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, now: datetime | None = None) -> list[str]:
        """Enqueue all tasks whose schedule is currently due.

        Each due entry has its actor called with ``actor.send(*args, **kwargs)``
        and its ``last_run_at`` updated to *now* so it is not re-enqueued
        until the next trigger time.

        Args:
            now: Reference UTC datetime.  Defaults to
                 ``datetime.now(timezone.utc)`` when ``None``.

        Returns:
            Sorted list of entry names that were successfully enqueued.
        """
        _now = now if now is not None else datetime.now(UTC)
        enqueued: list[str] = []

        for entry in self._registry.all_due(_now):
            try:
                entry.actor.send(*entry.args, **entry.kwargs)
                entry.last_run_at = _now
                enqueued.append(entry.name)
                logger.debug(
                    "Enqueued scheduled task %r (schedule=%s)",
                    entry.name,
                    entry.schedule,
                )
            except Exception as exc:
                logger.error(
                    "Failed to enqueue scheduled task %r: %s",
                    entry.name,
                    exc,
                )

        return sorted(enqueued)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_registry(self) -> ScheduleRegistry:
        """Return the underlying :class:`~openviper.tasks.registry.ScheduleRegistry`."""
        return self._registry

    def all_entries(self) -> list[ScheduleEntry]:
        """Return all registered :class:`~openviper.tasks.registry.ScheduleEntry` objects."""
        return self._registry.all_entries()

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"Scheduler(entries={len(self._registry)})"
