"""Periodic task scheduler - integrates with openviper's built-in scheduler.

Uses :class:`openviper.tasks.core.Scheduler` (``CronSchedule`` /
``IntervalSchedule``) to fire ``@task``-decorated actors on a schedule.
The scheduler ticks in a daemon thread inside the worker process - no
separate beat process or third-party library is required.

Usage
-----
``@periodic`` automatically applies ``@task()`` when the decorated function
is not already a Dramatiq actor, so the simple form just works::

    from openviper.tasks import periodic

    @periodic(every=300)           # every 5 minutes
    async def sync_feeds():
        ...

    @periodic(cron="0 8 * * 1-5")  # weekdays at 08:00
    async def morning_report():
        ...

Stack ``@task()`` explicitly only when you need Dramatiq-specific options
such as a custom queue, retry policy, or time limit::

    from openviper.tasks import task, periodic

    @periodic(every=3600, run_on_start=True)
    @task(queue_name="maintenance", time_limit=30_000)
    async def purge_tmp_files():
        ...

    @periodic(every=60, args=(42,), kwargs={"dry_run": True})
    @task()
    async def poll(user_id: int, *, dry_run: bool = False):
        ...
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from openviper.tasks.core import Scheduler
from openviper.tasks.decorators import task as task_decorator
from openviper.tasks.schedule import CronSchedule, IntervalSchedule

if TYPE_CHECKING:
    from openviper.tasks.types import ActorProtocol, TaskCallable, TaskDecorator, TaskValue

logger = logging.getLogger("openviper.tasks")


@dataclass(slots=True)
class PeriodicRegistration:
    """Pending periodic task registration."""

    name: str
    actor: ActorProtocol
    schedule: CronSchedule | IntervalSchedule
    run_on_start: bool
    args: tuple[TaskValue, ...]
    kwargs: dict[str, TaskValue]


_pending: list[PeriodicRegistration] = []
_state_lock = threading.Lock()

# Active scheduler and tick thread (set by start_scheduler).
_scheduler: Scheduler | None = None
_tick_thread: threading.Thread | None = None
_stop_event = threading.Event()


def periodic(
    every: int | float | None = None,
    cron: str | None = None,
    *,
    run_on_start: bool = False,
    name: str | None = None,
    args: tuple[TaskValue, ...] = (),
    kwargs: dict[str, TaskValue] | None = None,
) -> TaskDecorator:
    """Schedule a ``@task``-decorated actor to run automatically.

    If the decorated function is not already a Dramatiq actor, ``@task()``
    is applied automatically with default options.  Stack ``@task()``
    explicitly only when you need custom queue, retry, or time-limit settings.

    Args:
        every:        Interval in **seconds** between consecutive runs.
        cron:         Five-field cron expression
                      (``"minute hour dom month dow"``).
        run_on_start: Enqueue the task once immediately when the worker
                      starts before the first scheduled tick.
        name:         Registry name for this entry.  Defaults to the
                      actor's ``actor_name``.  Must be unique across all
                      ``@periodic`` registrations.
        args:         Positional arguments forwarded to ``actor.send()``.
        kwargs:       Keyword arguments forwarded to ``actor.send()``.

    Raises:
        ValueError: If neither *every* nor *cron* is supplied.
    """
    if every is None and cron is None:
        raise ValueError("periodic() requires 'every' (seconds) or 'cron' (cron expression).")

    def decorator(actor: TaskCallable | ActorProtocol) -> ActorProtocol:
        # Auto-wrap plain functions with @task() so users don't have to stack
        # @task() explicitly when no Dramatiq-specific options are needed.
        if not hasattr(actor, "actor_name"):
            actor = task_decorator()(cast("TaskCallable", actor))
        typed_actor = cast("ActorProtocol", actor)
        entry_name = name or typed_actor.actor_name
        schedule: IntervalSchedule | CronSchedule
        if every is not None:
            schedule = IntervalSchedule(float(every))
        elif cron is not None:
            schedule = CronSchedule(cron)
        else:
            raise ValueError("periodic() requires 'every' or 'cron'.")
        registration = PeriodicRegistration(
            name=entry_name,
            actor=typed_actor,
            schedule=schedule,
            run_on_start=run_on_start,
            args=args,
            kwargs=dict(kwargs or {}),
        )
        with _state_lock:
            _pending.append(registration)
        logger.debug(
            "Registered periodic task %r  every=%s  cron=%s  run_on_start=%s",
            entry_name,
            every,
            cron,
            run_on_start,
        )
        return typed_actor

    return cast("TaskDecorator", decorator)


def start_scheduler() -> None:
    """Register all pending entries and start the tick thread.

    Called by :func:`openviper.tasks.worker.run_worker` after the Dramatiq
    worker has started.  Safe to call when the registry is empty.
    """
    global _scheduler, _tick_thread

    with _state_lock:
        pending = tuple(_pending)

    if not pending:
        return

    if _tick_thread is not None and _tick_thread.is_alive():
        logger.debug("Scheduler tick thread already running - skipping start.")
        return

    _scheduler = Scheduler()
    for entry in pending:
        _scheduler.add(
            entry.name,
            entry.actor,
            entry.schedule,
            args=entry.args,
            kwargs=entry.kwargs,
            replace=True,  # safe on worker reload; avoids ValueError from stale registry
        )
        if entry.run_on_start:
            enqueue_now(entry.actor, entry.name, entry.args, entry.kwargs)

    _stop_event.clear()
    _tick_thread = threading.Thread(
        target=tick_loop,
        daemon=True,
        name="openviper.tasks.scheduler",
    )
    _tick_thread.start()

    noun = "task" if len(pending) == 1 else "tasks"
    logger.info("Periodic scheduler started - %d %s registered.", len(pending), noun)


def stop_scheduler() -> None:
    """Stop the tick thread.

    Called by :func:`openviper.tasks.worker.run_worker` on shutdown.
    """
    global _scheduler, _tick_thread

    _stop_event.set()

    if _tick_thread is not None:
        _tick_thread.join(timeout=2)
        _tick_thread = None

    _scheduler = None
    logger.debug("Periodic scheduler stopped.")


def reset_scheduler() -> None:
    """Stop the scheduler and clear all pending registrations.

    Primarily for tests - call this in teardown to ensure a clean slate
    between test cases that register ``@periodic`` tasks.
    """
    stop_scheduler()
    with _state_lock:
        _pending.clear()
    _stop_event.clear()


def tick_loop() -> None:
    """Daemon thread: call scheduler.tick() every second until stopped."""
    while not _stop_event.wait(1.0):
        if _scheduler is None:
            break
        try:
            fired = _scheduler.tick()
            for entry_name in fired:
                logger.debug("Periodic task enqueued: %s", entry_name)
        except Exception as exc:
            logger.warning("Scheduler tick error: %s", exc)


def enqueue_now(
    actor: ActorProtocol,
    name: str,
    args: tuple[TaskValue, ...],
    kwargs: dict[str, TaskValue],
) -> None:
    """Fire a task immediately (used for run_on_start)."""
    try:
        actor.send(*args, **kwargs)
        logger.debug("Periodic task enqueued on start: %s", name)
    except Exception as exc:
        logger.warning("Failed to enqueue periodic task %s on start: %s", name, exc)
