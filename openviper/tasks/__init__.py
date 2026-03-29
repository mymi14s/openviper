"""Background task system for OpenViper, powered by Dramatiq.

Quick-start
-----------
Define a task::

    from openviper.tasks import task

    @task(queue_name="default", max_retries=3)
    async def send_welcome_email(user_id: int) -> None:
        user = await User.objects.get(id=user_id)
        await send_email(user.email, "Welcome!")

Enqueue it::

    send_welcome_email.send(user_id)        # fire and forget
    send_welcome_email.delay(user_id)       # alias for .send()
    send_welcome_email.send_with_options(   # with a 10-second delay
        args=(user_id,), delay=10_000
    )

Query results::

    from openviper.tasks import get_task_result, list_task_results

    result = await get_task_result(message_id)
    # {"status": "success", "result": "...", "completed_at": "...", ...}

    failures = await list_task_results(status="failure", limit=20)

Start the worker::

    python viperctl.py runworker
    python viperctl.py runworker --threads 16 --queues emails notifications
"""

from __future__ import annotations

import logging
import os

from openviper.db.events import ModelEventDispatcher, get_dispatcher, reset_dispatcher
from openviper.tasks.broker import get_broker, reset_broker, setup_broker
from openviper.tasks.core import Scheduler
from openviper.tasks.decorators import task
from openviper.tasks.log import configure_worker_logging_from_settings
from openviper.tasks.middleware import reset_tracking_buffer
from openviper.tasks.registry import ScheduleEntry, ScheduleRegistry, get_registry, reset_registry
from openviper.tasks.results import (
    get_task_result,
    get_task_result_sync,
    list_task_results,
    list_task_results_sync,
    reset_engine,
)
from openviper.tasks.schedule import CronSchedule, IntervalSchedule, Schedule
from openviper.tasks.scheduler import periodic, reset_scheduler

# When this module is imported inside a worker process (``OPENVIPER_WORKER=1``
# is set by ``runworker`` before anything else runs):
#   1. Configure file logging immediately so every subsequent log statement
#      lands in ``logs/worker.log``.
#   2. Eagerly initialise the broker so middleware (SchedulerMiddleware,
#      TaskTrackingMiddleware) is attached *before* user modules are imported
#      by the dramatiq CLI.  Without this, broker creation is deferred to the
#      first ``@task`` decorator in a user module — if that module fails to
#      import, no broker is ever created and the worker silently does nothing.
if os.environ.get("OPENVIPER_WORKER"):
    configure_worker_logging_from_settings()

    try:
        setup_broker()  # noqa: F821  # already imported at top-level
    except Exception as _exc:
        logging.getLogger("openviper.tasks").warning("Worker: eager broker setup failed — %s", _exc)

__all__ = [
    # Decorators
    "task",
    "periodic",
    # Broker helpers
    "get_broker",
    "setup_broker",
    "reset_broker",
    # Scheduler
    "Scheduler",
    "Schedule",
    "CronSchedule",
    "IntervalSchedule",
    "ScheduleEntry",
    "ScheduleRegistry",
    "get_registry",
    "reset_registry",
    # Result queries — async
    "get_task_result",
    "list_task_results",
    # Result queries — sync
    "get_task_result_sync",
    "list_task_results_sync",
    # Test teardown helpers
    "reset_engine",
    "reset_scheduler",
    "reset_tracking_buffer",
    "reset_dispatcher",
    # Model event dispatcher
    "ModelEventDispatcher",
    "get_dispatcher",
]
