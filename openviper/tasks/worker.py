"""Dramatiq worker wrapper with signal handling.

Started by the ``start-worker`` management command in a dedicated process.
"""

from __future__ import annotations

import signal
import threading

import dramatiq

from openviper.tasks.broker import get_broker
from openviper.tasks.logging import get_task_logger

logger = get_task_logger("openviper.tasks.worker")

shutdown_event = threading.Event()


def run_worker(
    *,
    processes: int = 1,
    threads: int = 8,
    queues: list[str] | None = None,
) -> None:
    """Start the Dramatiq worker process.

    Args:
        processes: Worker process count (API compat; Dramatiq 2.x ignores this).
        threads: Threads per process (``worker_threads``).
        queues: Specific queues to consume. ``None`` consumes all.
    """
    shutdown_event.clear()

    broker = get_broker()

    worker = dramatiq.Worker(
        broker,
        worker_threads=threads,
        queues=set(queues) if queues else None,
    )
    worker.start()

    def term_handler(signum: int, frame: object) -> None:
        if not shutdown_event.is_set():
            print("Stopping worker...")
            shutdown_event.set()
        else:
            print("Killing worker...")
            raise SystemExit(1)

    signal.signal(signal.SIGINT, term_handler)
    signal.signal(signal.SIGTERM, term_handler)

    try:
        shutdown_event.wait()
    except SystemExit:
        pass
    finally:
        worker.stop()
        logger.info("Worker stopped.")
