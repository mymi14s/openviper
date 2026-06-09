"""Dramatiq middleware for database cleanup, state observation, and context logging.

Each class inherits from :class:`dramatiq.Middleware` and implements the
standard hook protocol: ``before_process_message``, ``after_process_message``,
and ``after_skip_message``.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import traceback
import typing as t
import uuid

import dramatiq.middleware.middleware as dramatiq_middleware

from openviper.db.backends.registry import backend_registry
from openviper.tasks.logging import get_task_logger
from openviper.tasks.models import TaskResult

logger = get_task_logger("openviper.tasks.middleware")

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "openviper.tasks.trace_id", default=""
)

start_time_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "openviper.tasks.start_time", default=0.0
)


class DatabaseCleanupMiddleware(dramatiq_middleware.Middleware):
    """Close stale connections and roll back failed transactions after each task."""

    def before_process_message(
        self,
        broker: t.Any,
        message: t.Any,
    ) -> None:
        logger.debug(
            "DatabaseCleanupMiddleware: before_process_message for %s",
            message.actor_name,
        )

    def after_process_message(
        self,
        broker: t.Any,
        message: t.Any,
        *,
        result: t.Any = None,
        exception: BaseException | None = None,
    ) -> None:
        if exception is not None:
            self.rollback_and_close()
        else:
            self.close_stale_connections()

    def after_skip_message(self, broker: t.Any, message: t.Any) -> None:
        self.close_stale_connections()

    def close_stale_connections(self) -> None:
        """Close idle database connections left open after task execution."""
        try:
            for backend in backend_registry._backends.values():
                if hasattr(backend, "close_idle_connections"):
                    backend.close_idle_connections()
        except Exception:
            logger.debug("No database backends to clean up")

    def rollback_and_close(self) -> None:
        """Roll back uncommitted transactions and close stale connections."""
        try:
            for backend in backend_registry._backends.values():
                if hasattr(backend, "rollback"):
                    backend.rollback()
                if hasattr(backend, "close_idle_connections"):
                    backend.close_idle_connections()
        except Exception:
            logger.debug("No database backends to roll back")


class StateObservationMiddleware(dramatiq_middleware.Middleware):
    """Record task state transitions into ``TaskResult``."""

    def before_process_message(
        self,
        broker: t.Any,
        message: t.Any,
    ) -> None:
        start_time_var.set(time.monotonic())
        actor_name = getattr(message, "actor_name", "unknown")
        logger.info("Actor %s state: running", actor_name)
        self.upsert_task_result(message, status="running")

    def after_process_message(
        self,
        broker: t.Any,
        message: t.Any,
        *,
        result: t.Any = None,
        exception: BaseException | None = None,
    ) -> None:
        duration_ms = self.elapsed_ms()
        actor_name = getattr(message, "actor_name", "unknown")
        if exception is not None:
            retries = getattr(message, "options", {}).get("retries", 0)
            status = "dead" if retries >= 3 else "failure"
            logger.info("Actor %s state: %s (duration=%sms)", actor_name, status, duration_ms)
            self.upsert_task_result(
                message,
                status=status,
                error_traceback=traceback.format_exc(),
                retries=retries,
                duration_ms=duration_ms,
            )
        else:
            logger.info("Actor %s state: success (duration=%sms)", actor_name, duration_ms)
            self.upsert_task_result(
                message, status="success", result=result, duration_ms=duration_ms
            )

    def after_skip_message(self, broker: t.Any, message: t.Any) -> None:
        self.upsert_task_result(message, status="skipped")

    def elapsed_ms(self) -> int | None:
        """Return elapsed ms since ``before_process_message``, or None."""
        start = start_time_var.get(0.0)
        if start:
            return int((time.monotonic() - start) * 1000)
        return None

    def upsert_task_result(
        self,
        message: t.Any,
        *,
        status: str,
        result: t.Any = None,
        error_traceback: str | None = None,
        retries: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        """Insert or update a ``TaskResult`` row for *message*."""
        try:
            message_id = str(getattr(message, "message_id", uuid.uuid4()))
            actor_name = getattr(message, "actor_name", "")
            queue_name = getattr(message, "queue_name", "default")
            args = getattr(message, "args", None)

            async def persist() -> None:
                existing = await TaskResult.objects.filter(message_id=message_id).first()
                if existing:
                    updates: dict[str, t.Any] = {"status": status}
                    if result is not None:
                        updates["return_value"] = result
                    if error_traceback is not None:
                        updates["error_traceback"] = error_traceback
                    if duration_ms is not None:
                        updates["duration_ms"] = duration_ms
                    updates["retries"] = retries
                    await TaskResult.objects.filter(message_id=message_id).update(**updates)
                else:
                    await TaskResult.objects.create(
                        message_id=message_id,
                        actor_name=actor_name,
                        queue=queue_name,
                        arguments=args if isinstance(args, dict) else None,
                        status=status,
                        retries=retries,
                        duration_ms=duration_ms,
                    )

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(persist())
            except RuntimeError:
                asyncio.run(persist())
        except Exception:
            logger.debug(
                "StateObservationMiddleware: skipping TaskResult persist for %s",
                getattr(message, "actor_name", "unknown"),
            )


class UnifiedContextLogger(dramatiq_middleware.Middleware):
    """Bind a trace ID to all log lines within a task execution scope."""

    def before_process_message(
        self,
        broker: t.Any,
        message: t.Any,
    ) -> None:
        trace_id = str(uuid.uuid4())[:8]
        trace_id_var.set(trace_id)
        actor_name = getattr(message, "actor_name", "unknown")
        logger.info("[%s] Running actor: %s", trace_id, actor_name)

    def after_process_message(
        self,
        broker: t.Any,
        message: t.Any,
        *,
        result: t.Any = None,
        exception: BaseException | None = None,
    ) -> None:
        actor_name = getattr(message, "actor_name", "unknown")
        if exception is not None:
            logger.info("Actor %s failed: %s", actor_name, exception)
        else:
            logger.info("Actor %s completed successfully", actor_name)


def get_trace_id() -> str:
    """Return the current task trace ID from the context variable."""
    return trace_id_var.get("")
