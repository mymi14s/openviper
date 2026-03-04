"""Blocking run-loop for OpenViper's periodic task scheduler.

:func:`run_scheduler` is the entry-point called by the ``runworker``
management command.  It ticks the scheduler at *tick_interval* second
intervals and handles ``SIGINT`` / ``SIGTERM`` for a clean shutdown.

There is **no subprocess** — the scheduler runs entirely in-process, which
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
import sys
import time
from datetime import datetime, timezone
from typing import Any

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
    _scheduler: Scheduler = scheduler if scheduler is not None else Scheduler()

    logger.info("=" * 60)
    logger.info("OpenViper scheduler starting  (tick_interval=%.2fs)", tick_interval)
    logger.info("Registered entries: %d", len(_scheduler))
    logger.info("=" * 60)

    _running = True

    def _shutdown(signum: int, frame: Any) -> None:
        nonlocal _running
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down scheduler…", sig_name)
        _running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while _running:
            now = datetime.now(timezone.utc)
            enqueued = _scheduler.tick(now)
            if enqueued:
                logger.debug("Tick enqueued: %s", enqueued)
            time.sleep(tick_interval)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Scheduler stopped.")
        sys.exit(0)
