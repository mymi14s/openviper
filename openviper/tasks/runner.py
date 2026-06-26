"""Worker lifecycle: validate, discover, schedule, run.

Entry point for the ``start-worker`` management command.
"""

from __future__ import annotations

import asyncio
import importlib
import typing as t

import dramatiq
import dramatiq.errors as dramatiq_errors
from dramatiq.asyncio import get_event_loop_thread
from dramatiq.middleware.asyncio import AsyncIO

from openviper.conf import settings
from openviper.db.connection import close_db, reset_engine
from openviper.tasks.broker import get_broker
from openviper.tasks.conf import resolve_tasks_config, validate_tasks_config
from openviper.tasks.discovery import discover_tasks
from openviper.tasks.logging import configure_task_logging, get_task_logger
from openviper.tasks.middleware import (
    DatabaseCleanupMiddleware,
    StateObservationMiddleware,
    UnifiedContextLogger,
)
from openviper.tasks.registry import Registry
from openviper.tasks.schedule import sync_scheduled_jobs
from openviper.tasks.scheduler import Scheduler
from openviper.tasks.worker import run_worker

logger = get_task_logger("openviper.tasks.runner")

BUILTIN_TASK_MODULES: list[str] = [
    "openviper.core.email.queue",
]


async def sync_and_close() -> None:
    """Run scheduled-job sync and dispose the engine on the same event loop.

    Both operations must run on the same event loop so that aioodbc
    connections created during sync can be properly closed before the
    loop is torn down.  Without this, ``asyncio.run()`` closes the loop
    while aioodbc connections are still open, producing "Unclosed
    connection" warnings.
    """
    try:
        await sync_scheduled_jobs()
    finally:
        await close_db()


def run(
    *,
    processes: int = 1,
    threads: int = 8,
    queues: list[str] | None = None,
    installed_apps: tuple[str, ...] | list[str] | None = None,
    no_scheduler: bool = False,
) -> None:
    """Full worker lifecycle: validate, discover, schedule, run.

    Args:
        processes: Number of Dramatiq worker processes.
        threads: Number of threads per process.
        queues: Specific queues to consume.
        installed_apps: Override for ``settings.INSTALLED_APPS``.
        no_scheduler: When True, skip the scheduler thread.  Only one
            worker should run the scheduler to avoid duplicate enqueues.
    """
    cfg = resolve_tasks_config(settings.TASKS if isinstance(settings.TASKS, dict) else {})
    validate_tasks_config(cfg)

    configure_task_logging(cfg, worker_mode=True)

    broker = get_broker()

    broker.add_middleware(AsyncIO())
    broker.add_middleware(DatabaseCleanupMiddleware())

    log_cfg = cfg.get("logging", {})
    db_cfg = log_cfg.get("database") if isinstance(log_cfg, dict) else None
    if isinstance(db_cfg, dict) and db_cfg.get("task", 0):
        broker.add_middleware(StateObservationMiddleware())

    broker.add_middleware(UnifiedContextLogger())

    if installed_apps is None:
        installed_apps = t.cast("tuple[str, ...]", settings.INSTALLED_APPS)
    discover_tasks(list(installed_apps))

    # Framework task modules outside any installed app.
    registry = Registry()
    for module_name in BUILTIN_TASK_MODULES:
        if not registry.is_discovered(module_name):
            try:
                importlib.import_module(module_name)
                registry.mark_discovered(module_name)
                print(f"Discovered built-in tasks module: {module_name}")
            except ModuleNotFoundError:
                logger.debug("Built-in tasks module %s not found", module_name)
            except Exception:
                logger.exception("Error importing %s", module_name)

    for actor_name, fn in registry.actors.items():
        try:
            broker.get_actor(actor_name)
        except dramatiq_errors.ActorNotFound:
            queue = registry.get_actor_queue(actor_name)
            actor_opts = registry.get_actor_options(actor_name)
            dramatiq.actor(
                actor_name=actor_name, queue_name=queue, **actor_opts
            )(fn)

    try:
        asyncio.run(sync_and_close())
    except Exception:
        logger.exception("Failed to synchronise scheduled jobs")

    scheduler = None
    if not no_scheduler:
        scheduler = Scheduler()
        scheduler.start()

    queues_display = queues or ["default"]
    scheduler_status = "disabled" if no_scheduler else "enabled"
    print(
        f"Worker started: processes={processes} threads={threads} "
        f"queues={queues_display} scheduler={scheduler_status}"
    )

    try:
        run_worker(processes=processes, threads=threads, queues=queues)
    except KeyboardInterrupt:
        print("Worker interrupted, shutting down...")
    except SystemExit:
        print("Worker forced to exit")
    finally:
        if scheduler is not None:
            scheduler.stop()
        dispose_worker_engine()
        print("Worker shutdown complete.")


def dispose_worker_engine() -> None:
    """Dispose the DB engine on the worker's EventLoopThread before exit."""
    try:
        elt = get_event_loop_thread()
        if elt is not None and elt.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(close_db(), elt.loop)
            future.result(timeout=5.0)
        else:
            asyncio.run(close_db())
    except Exception:
        logger.debug("Engine disposal on worker shutdown failed", exc_info=True)
        reset_engine()
