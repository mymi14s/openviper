"""In-process Dramatiq worker for openviper.

:func:`run_worker` is the single entry-point called by the ``runworker``
management command.  It:

1. Sets up file logging (``logs/worker.log``).
2. Discovers and imports all task modules from ``INSTALLED_APPS`` so that
   actor registrations happen before the broker is used.
3. Initialises the broker (Redis / RabbitMQ / Stub).
4. Starts a :class:`dramatiq.Worker` in the current process.
5. Blocks until SIGINT / SIGTERM, then shuts down cleanly.

There is **no subprocess**.  The worker runs entirely in-process, which
makes debugging straightforward and avoids the PYTHONPATH / settings
propagation issues that a subprocess approach introduces.

Discovery strategy
------------------
For each app in ``INSTALLED_APPS`` (skipping ``openviper.*`` internals) the
worker walks the app directory and imports every ``.py`` file that is not
``__init__.py`` and not inside ``migrations/``, ``tests/``, or
``__pycache__``.  Actors registered by ``@task`` decorators during those
imports are automatically picked up by the broker.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import signal
import sys
import time
from typing import Any

from dramatiq.worker import Worker

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.tasks.broker import setup_broker
from openviper.tasks.log import configure_worker_logging_from_settings
from openviper.tasks.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger("openviper.tasks")

_SKIP_DIRS: frozenset[str] = frozenset(
    {"migrations", "tests", "__pycache__", ".git", "static", "templates"}
)
_SKIP_FILES: frozenset[str] = frozenset(
    {
        # Project configuration
        "asgi.py",
        "wsgi.py",
        "settings.py",
        "routes.py",
        "urls.py",
        # Framework layer files — rarely contain task definitions
        "models.py",
        "views.py",
        "admin.py",
        "serializers.py",
        "decorators.py",
        "forms.py",
        "filters.py",
        "permissions.py",
        "pagination.py",
        "signals.py",
        "apps.py",
        "validators.py",
    }
)


# ---------------------------------------------------------------------------
# Task discovery
# ---------------------------------------------------------------------------


def discover_tasks(extra_modules: list[str] | None = None) -> list[str]:
    """Import task modules from every app in ``INSTALLED_APPS``.

    Args:
        extra_modules: Additional dotted module paths to import on top of
                       the auto-discovered ones.

    Returns:
        Sorted list of module paths that were successfully imported.
    """
    resolver = AppResolver()
    app_names: list[str] = list(getattr(settings, "INSTALLED_APPS", []))
    imported: list[str] = []

    for app_name in app_names:
        if app_name.startswith("openviper."):
            continue  # skip framework internals

        app_path, found = resolver.resolve_app(app_name)
        if not (found and app_path):
            logger.debug("Could not resolve app path for %s, skipping.", app_name)
            continue

        for root, dirs, files in os.walk(app_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            for filename in files:
                if (
                    not filename.endswith(".py")
                    or filename in _SKIP_FILES
                    or filename == "__init__.py"
                ):
                    continue

                rel = os.path.relpath(os.path.join(root, filename), app_path)
                submodule = rel[:-3].replace(os.sep, ".")
                module_path = f"{app_name}.{submodule}"

                try:
                    importlib.import_module(module_path)
                    imported.append(module_path)
                    logger.debug("Imported %s", module_path)
                except Exception as exc:
                    logger.warning("Could not import %s: %s", module_path, exc)

    # Import any explicitly requested extra modules.
    for module_path in extra_modules or []:
        try:
            importlib.import_module(module_path)
            imported.append(module_path)
            logger.debug("Imported extra module %s", module_path)
        except Exception as exc:
            logger.warning("Could not import extra module %s: %s", module_path, exc)

    imported.sort()
    logger.info("Task discovery complete — %d modules imported.", len(imported))
    return imported


# ---------------------------------------------------------------------------
# Worker entry-point
# ---------------------------------------------------------------------------


def run_worker(
    processes: int = 1,
    threads: int = 8,
    queues: list[str] | None = None,
    extra_modules: list[str] | None = None,
) -> None:
    """Start the Dramatiq worker and block until a shutdown signal.

    Args:
        processes:     Number of worker processes (in-process mode uses 1).
        threads:       Number of worker threads to spawn.
        queues:        Restrict processing to these queue names.  ``None``
                       means consume from all declared queues.
        extra_modules: Extra Python modules to import in addition to those
                       found by auto-discovery.
    """
    os.environ.setdefault("OPENVIPER_WORKER", "1")
    configure_worker_logging_from_settings()

    task_cfg: dict = dict(getattr(settings, "TASKS", {}) or {})

    logger.info("OPENVIPER_WORKER environment variable set — worker logging enabled.")

    # Master enable gate — worker does nothing unless explicitly enabled.
    if not bool(task_cfg.get("enabled", False)):
        logger.warning(
            "Task worker is disabled. "
            "Add TASKS['enabled'] = 1 to your settings to start the worker."
        )
        return

    logger.info("=" * 60)
    logger.info("OpenViper task worker starting")
    logger.info("=" * 60)

    scheduler_enabled: bool = bool(task_cfg.get("scheduler_enabled", False))

    # Discover task modules BEFORE getting the broker so that all @task
    # decorators fire (and register actors) while the broker is initialised.
    discover_tasks(extra_modules)

    broker = setup_broker()

    worker = Worker(
        broker,
        worker_threads=threads,
        queues=set(queues) if queues else None,
    )

    # ── Signal handlers ──────────────────────────────────────────────────────
    # Raise SystemExit so the except/finally block below handles all cleanup
    # in one place.  worker.stop() must NOT be called here; it runs in finally.

    def _shutdown(signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down…", sig_name)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    worker.start()
    if scheduler_enabled:
        start_scheduler()
    else:
        logger.info("Periodic scheduler disabled (set TASKS['scheduler_enabled'] = 1 to enable).")

    declared = sorted(broker.get_declared_queues())
    active_queues = ", ".join(queues or declared) or "all"
    logger.info("Worker ready — queues: %s | threads: %d", active_queues, threads)
    logger.info("Press Ctrl-C to stop.")

    # ── Main loop ────────────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if scheduler_enabled:
            stop_scheduler()
        logger.info("Stopping worker (timeout 30 s)…")
        with contextlib.suppress(Exception):
            worker.stop(timeout=30_000)
        logger.info("Worker exited.")
