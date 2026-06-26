"""Dramatiq worker wrapper with signal handling.

Started by the ``start-worker`` management command in a dedicated process.
"""

from __future__ import annotations

import asyncio
import signal
import threading

import dramatiq
from dramatiq.asyncio import EventLoopThread, get_event_loop_thread, set_event_loop_thread

from openviper.db.connection import dispose_engine
from openviper.db.connections import connections
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

    if get_event_loop_thread() is None:
        event_loop_thread = EventLoopThread(logger=logger)
        event_loop_thread.start()
        set_event_loop_thread(event_loop_thread)
        logger.info("EventLoopThread started for async actors")

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

        # Dispose database connections before stopping the event loop.
        elt = get_event_loop_thread()
        if connections.initialized:
            temp_loop = False
            try:
                if elt is not None:
                    loop = elt.loop
                else:
                    loop = asyncio.new_event_loop()
                    temp_loop = True
                loop.run_until_complete(connections.disconnect_all())
            except Exception:
                logger.warning("Error during database cleanup", exc_info=True)
            finally:
                if temp_loop:
                    loop.close()

        temp_loop = False
        try:
            if elt is not None:
                loop = elt.loop
            else:
                loop = asyncio.new_event_loop()
                temp_loop = True
            loop.run_until_complete(dispose_engine())
        except Exception:
            logger.warning("Error during engine cleanup", exc_info=True)
        finally:
            if temp_loop:
                loop.close()

        if elt is not None:
            elt.stop()
        logger.info("Worker stopped.")
