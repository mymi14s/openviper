"""
Background scheduler that enqueues periodic tasks on schedule.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import threading
import time
import typing as t

from croniter import croniter
from dramatiq.asyncio import get_event_loop_thread

from openviper.db.models import Q
from openviper.tasks.decorators import enqueue_task
from openviper.tasks.logging import get_task_logger
from openviper.tasks.models import ScheduledJob
from openviper.tasks.periodic import parse_interval
from openviper.tasks.registry import Registry
from openviper.utils import timezone

logger = get_task_logger("openviper.tasks.scheduler")

TICK_INTERVAL = 1.0

DEDUP_THRESHOLD_SECONDS = 2


def run_async(coro: t.Coroutine[t.Any, t.Any, t.Any]) -> t.Any:
    """
    Execute *coro* on the worker's EventLoopThread or a fallback loop.
    """
    elt = get_event_loop_thread()
    if elt is not None and elt.loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, elt.loop)
        return future.result(timeout=10.0)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=10.0)
    return asyncio.run(coro)


def compute_next_cron_fire(cron_expr: str, base: datetime.datetime) -> datetime.datetime:
    """Return the next fire time for *cron_expr* after *base*.

    Raises ``ImportError`` when ``croniter`` is not installed.
    Raises ``ValueError`` for invalid cron expressions.
    """
    result = croniter(cron_expr, base).get_next(datetime.datetime)
    if isinstance(result, datetime.datetime):
        return result
    logger.warning(
        "croniter returned %s for '%s' - falling back to 1-minute interval",
        type(result).__name__,
        cron_expr,
    )
    return base.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)


class Scheduler:
    """Daemon-thread scheduler for ``every`` and ``cron`` periodic jobs."""

    def __init__(self) -> None:
        self.running_event = threading.Event()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the scheduler daemon thread."""
        if self.thread is not None and self.thread.is_alive():
            return
        self.running_event.set()
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self.run_loop,
            name="openviper-scheduler",
            daemon=True,
        )
        self.thread.start()
        print("Scheduler thread started")

    def stop(self) -> None:
        """Signal stop and join the scheduler thread."""
        self.running_event.clear()
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            self.thread = None
        logger.info("Scheduler thread stopped")

    def run_loop(self) -> None:
        """Evaluate periodic schedules every tick interval."""
        registry = Registry()
        last_fired: dict[str, float] = {}
        next_cron_fire: dict[str, datetime.datetime] = {}

        now = time.monotonic()
        now_dt = timezone.now()
        for name, entry in registry.periodic_jobs.items():
            cron = entry.get("cron")
            every = entry.get("every")
            if cron is not None:
                try:
                    next_cron_fire[name] = compute_next_cron_fire(cron, now_dt)
                except (ImportError, ValueError):
                    logger.exception(
                        "Failed to compute initial fire time for '%s' "
                        "with cron '%s' - skipping schedule",
                        name,
                        cron,
                    )
            elif every is not None:
                try:
                    interval = parse_interval(every)
                except ValueError:
                    continue
                last_fired[name] = now

        startup_jobs = [entry for entry in registry.periodic_jobs.values() if entry.get("startup")]
        for job in startup_jobs:
            self.enqueue_periodic(job)
            last_fired[job["name"]] = time.monotonic()

        while self.running_event.is_set():
            now = time.monotonic()
            now_dt = timezone.now()
            for name, entry in registry.periodic_jobs.items():
                cron = entry.get("cron")
                every = entry.get("every")

                if cron is not None:
                    nxt = next_cron_fire.get(name)
                    if nxt is not None and nxt <= now_dt:
                        if self.claim_enqueue(name):
                            self.enqueue_periodic(entry)
                            last_fired[name] = now
                        try:
                            next_cron_fire[name] = compute_next_cron_fire(cron, now_dt)
                        except (ImportError, ValueError):
                            logger.exception(
                                "Failed to compute next fire time for '%s' "
                                "with cron '%s' - deactivating schedule",
                                name,
                                cron,
                            )
                            next_cron_fire.pop(name, None)
                            continue
                elif every is not None:
                    try:
                        interval = parse_interval(every)
                    except ValueError:
                        continue
                    last = last_fired.get(name, now)
                    if now - last >= interval and self.claim_enqueue(name):
                        self.enqueue_periodic(entry)
                        last_fired[name] = now
            self.stop_event.wait(TICK_INTERVAL)

    def claim_enqueue(self, name: str) -> bool:
        """Atomically claim enqueue rights via conditional UPDATE on
        ``ScheduledJob.last_enqueued_at``.

        Returns ``True`` when this worker won the claim, ``False`` when
        another worker already enqueued within the dedup threshold.
        """
        try:

            async def atomic_claim() -> bool:
                now_dt = timezone.now()
                threshold = now_dt - datetime.timedelta(
                    seconds=DEDUP_THRESHOLD_SECONDS,
                )
                updated = await ScheduledJob.objects.filter(
                    Q(last_enqueued_at__isnull=True) | Q(last_enqueued_at__lt=threshold),
                    name=name,
                    ignore_permissions=True,
                ).update(last_enqueued_at=now_dt)
                if updated == 0:
                    logger.debug(
                        "Job %s already claimed by another worker - skipping",
                        name,
                    )
                    return False
                return True

            result: bool = run_async(atomic_claim())
            return result
        except Exception:
            logger.warning("Dedup check failed for %s - allowing enqueue", name, exc_info=True)
            return True

    def enqueue_periodic(self, entry: dict[str, t.Any]) -> None:
        """Dispatch a periodic job message through the broker."""
        name = entry["name"]

        try:
            enqueue_task(name, (), {}, queue_name="default")
            logger.info("Enqueued periodic job: %s", name)
        except Exception:
            logger.exception("Failed to enqueue periodic job: %s", name)
