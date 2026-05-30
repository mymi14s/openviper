"""Blocking run-loop for OpenViper's periodic task scheduler.

:func:`run_scheduler` is the entry-point called by the ``start-worker``
management command.  It ticks the scheduler at *tick_interval* second
intervals and handles ``SIGINT`` / ``SIGTERM`` for a clean shutdown.

There is **no subprocess** - the scheduler runs entirely in-process, which
mirrors the design of :mod:`openviper.tasks.worker`.

Example (programmatic)::

    from openviper.tasks.core import Scheduler
    from openviper.tasks.runner import run_scheduler
    from openviper.tasks.schedule import CronSchedule

    scheduler = Scheduler()
    scheduler.add("nightly", nightly_report, CronSchedule("0 2 * * *"))

    run_scheduler(scheduler=scheduler)   # blocks until SIGINT/SIGTERM
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from types import FrameType

from openviper.tasks.core import Scheduler

logger = logging.getLogger("openviper.tasks")

__all__ = ["run_scheduler"]

_DEFAULT_TICK_INTERVAL: float = 1.0  # seconds


def run_scheduler(
    scheduler: Scheduler | None = None,
    tick_interval: float = _DEFAULT_TICK_INTERVAL,
) -> None:
    """Start the scheduler loop and block until a shutdown signal.

    Args:
        scheduler:     The :class:`~openviper.tasks.core.Scheduler` to tick.
                       A default (process-level) instance is created if not
                       provided.
        tick_interval: How often (in seconds) to call
                       :meth:`~openviper.tasks.core.Scheduler.tick`.
                       Lower values give finer resolution at the cost of more
                       CPU cycles; 1 second is sufficient for minute-granularity
                       cron expressions.
    """
    active_scheduler: Scheduler = scheduler if scheduler is not None else Scheduler()

    logger.info("=" * 60)
    logger.info("OpenViper scheduler starting  (tick_interval=%.2fs)", tick_interval)
    logger.info("Registered entries: %d", len(active_scheduler))
    logger.info("=" * 60)

    running = True

    def shutdown(signum: int, frame: FrameType | None) -> None:
        nonlocal running
        sig_name = signal.Signals(signum).name
        logger.info("Received %s - shutting down scheduler…", sig_name)
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while running:
            now = datetime.now(UTC)
            enqueued = active_scheduler.tick(now)
            if enqueued:
                logger.debug("Tick enqueued: %s", enqueued)
            time.sleep(tick_interval)
    except (KeyboardInterrupt, SystemExit):  # fmt: skip
        pass
    finally:
        logger.info("Scheduler stopped.")
