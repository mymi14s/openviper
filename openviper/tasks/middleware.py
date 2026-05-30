"""Dramatiq middleware for tracking task lifecycle events.

:class:`TaskTrackingMiddleware` hooks into every stage of a message's life
(enqueue → start → finish / fail) and persists the state to the
``openviper_task_results`` table via :mod:`openviper.tasks.results`.

Events are buffered in an in-process :class:`EventBuffer` and flushed to
the database in a single transaction either when the buffer reaches
``flush_threshold`` entries or when a terminal event (success, failure,
skipped, dead) is received.  This replaces the previous design of one
``upsert_result()`` call (= one DB round-trip) per lifecycle hook.

The middleware is designed to be *non-fatal*: every flush is wrapped so
that a tracking failure never kills the worker or the calling application.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import traceback as tb_module
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dramatiq.middleware import Middleware

from openviper.conf import settings
from openviper.tasks.results import batch_upsert_results
from openviper.tasks.scheduler import start_scheduler, stop_scheduler

if TYPE_CHECKING:
    from openviper.tasks.types import (
        BrokerProtocol,
        TaskFields,
        TaskMessageProtocol,
        WorkerProtocol,
    )

logger = logging.getLogger("openviper.tasks")

__all__ = ["TaskTrackingMiddleware", "SchedulerMiddleware", "reset_tracking_buffer"]

_TERMINAL_STATUSES = frozenset({"success", "failure", "skipped", "dead"})


def current_utc_time() -> datetime:
    return datetime.now(UTC)


@dataclasses.dataclass(slots=True)
class TrackingEvent:
    """A single task state transition to be persisted."""

    message_id: str
    fields: TaskFields
    terminal: bool


class EventBuffer:
    """Thread-safe buffer that batches task tracking events.

    Events are enqueued via :meth:`push`.  A flush is triggered when:

    * The event is terminal (success / failure / skipped / dead), or
    * The buffer size reaches ``flush_threshold``.

    Flushing calls :func:`~openviper.tasks.results.batch_upsert_results`
    with all buffered events in a single DB transaction, executed in a
    background thread to avoid blocking the worker.
    """

    def __init__(self, flush_threshold: int = 20) -> None:
        self._queue: deque[TrackingEvent] = deque()
        self._lock = threading.Lock()
        self.flush_threshold = flush_threshold
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="task_flush")

    def push(self, event: TrackingEvent) -> None:
        """Enqueue *event*; flush if terminal or threshold is reached."""
        with self._lock:
            self._queue.append(event)
            if event.terminal or len(self._queue) >= self.flush_threshold:
                events = list(self._queue)
                self._queue.clear()
            else:
                events = []
        if events:
            self._executor.submit(self._flush, events)

    def _flush(self, events: list[TrackingEvent]) -> None:
        """Write *events* to the results table in a single transaction."""
        try:
            batch_upsert_results([(e.message_id, e.fields) for e in events])
        except Exception as exc:
            logger.warning("EventBuffer flush failed: %s", exc)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the executor. Called on process exit."""
        self._executor.shutdown(wait=wait)


# Module-level singleton shared by all TaskTrackingMiddleware instances.
# Flush threshold via TASKS["tracking_flush_threshold"]
def get_flush_threshold() -> int:
    """Read the flush threshold from settings, with a default of 20."""
    try:
        task_cfg: dict[str, object] = getattr(settings, "TASKS", {}) or {}
        val = task_cfg.get("tracking_flush_threshold", 20)
        return int(val) if isinstance(val, (int, float, str)) else 20
    except Exception:
        return 20


_event_buffer = EventBuffer(flush_threshold=get_flush_threshold())


def reset_tracking_buffer() -> None:
    """Clear the event buffer and shutdown the executor.

    Call in test teardown to prevent state leakage.
    """
    global _event_buffer
    with _event_buffer._lock:
        _event_buffer._queue.clear()
    _event_buffer.shutdown(wait=True)
    # Create a new buffer with a fresh executor
    _event_buffer = EventBuffer()


class TaskTrackingMiddleware(Middleware):
    """Record task state transitions to the database via batched writes."""

    # ------------------------------------------------------------------
    # Enqueue side  (runs in the process that calls actor.send / .delay)
    # ------------------------------------------------------------------

    def before_enqueue(  # type: ignore[override]
        self, broker: BrokerProtocol, message: TaskMessageProtocol, delay: object
    ) -> None:
        del broker, delay
        try:
            _event_buffer.push(
                TrackingEvent(
                    message_id=message.message_id,
                    fields={
                        "actor_name": message.actor_name,
                        "queue_name": message.queue_name,
                        "args": list(message.args),
                        "kwargs": dict(message.kwargs),
                        "status": "pending",
                        "enqueued_at": current_utc_time(),
                    },
                    terminal=False,
                )
            )
        except Exception as exc:
            logger.warning("TaskTracking.before_enqueue: %s", exc)

    # ------------------------------------------------------------------
    # Worker side
    # ------------------------------------------------------------------

    def before_process_message(self, broker: BrokerProtocol, message: TaskMessageProtocol) -> None:  # type: ignore[override]
        del broker
        try:
            _event_buffer.push(
                TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "running", "started_at": current_utc_time()},
                    terminal=False,
                )
            )
            logger.info(
                "[%s] Starting  actor=%s queue=%s",
                message.message_id[:8],
                message.actor_name,
                message.queue_name,
            )
        except Exception as exc:
            logger.warning("TaskTracking.before_process_message: %s", exc)

    def after_process_message(  # type: ignore[override]
        self,
        broker: BrokerProtocol,
        message: TaskMessageProtocol,
        *,
        result: object = None,
        exception: BaseException | None = None,
    ) -> None:
        del broker
        try:
            now = current_utc_time()
            if exception is None:
                _event_buffer.push(
                    TrackingEvent(
                        message_id=message.message_id,
                        fields={
                            "status": "success",
                            "result": serialise(result),
                            "completed_at": now,
                        },
                        terminal=True,
                    )
                )
                logger.debug(
                    "[%s] Succeeded actor=%s",
                    message.message_id[:8],
                    message.actor_name,
                )
            else:
                _event_buffer.push(
                    TrackingEvent(
                        message_id=message.message_id,
                        fields={
                            "status": "failure",
                            "error": str(exception),
                            "traceback": tb_module.format_exc(),
                            "completed_at": now,
                        },
                        terminal=True,
                    )
                )
                logger.error(
                    "[%s] Failed    actor=%s  error=%s",
                    message.message_id[:8],
                    message.actor_name,
                    exception,
                )
        except Exception as exc:
            logger.warning("TaskTracking.after_process_message: %s", exc)

    def after_skip_message(self, broker: BrokerProtocol, message: TaskMessageProtocol) -> None:  # type: ignore[override]
        del broker
        try:
            _event_buffer.push(
                TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "skipped", "completed_at": current_utc_time()},
                    terminal=True,
                )
            )
        except Exception as exc:
            logger.warning("TaskTracking.after_skip_message: %s", exc)

    def after_nack(self, broker: BrokerProtocol, message: TaskMessageProtocol) -> None:  # type: ignore[override]
        """Called when a message is nacked (e.g. moved to the dead-letter queue)."""
        del broker
        try:
            _event_buffer.push(
                TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "dead", "completed_at": current_utc_time()},
                    terminal=True,
                )
            )
            logger.warning(
                "[%s] Dead-lettered  actor=%s",
                message.message_id[:8],
                message.actor_name,
            )
        except Exception as exc:
            logger.warning("TaskTracking.after_nack: %s", exc)


class SchedulerMiddleware(Middleware):
    """Start the periodic scheduler when the worker boots; stop it on shutdown.

    Attach this middleware to the broker so that ``@periodic`` tasks fire
    inside the worker process without requiring a separate beat process or
    parent-process discovery.  The ``after_worker_boot`` hook fires after
    all task modules have been imported and all ``@periodic`` registrations
    are in ``_pending``.
    """

    def after_worker_boot(self, broker: BrokerProtocol, worker: WorkerProtocol) -> None:  # type: ignore[override]
        del broker, worker
        try:
            start_scheduler()
        except Exception as exc:
            logger.warning("SchedulerMiddleware: could not start scheduler: %s", exc)

    def before_worker_shutdown(self, broker: BrokerProtocol, worker: WorkerProtocol) -> None:  # type: ignore[override]
        del broker, worker
        try:
            stop_scheduler()
        except Exception as exc:
            logger.debug("SchedulerMiddleware: error stopping scheduler: %s", exc)


def serialise(value: object) -> str | None:
    """Return a JSON string, or a safe truncated string if not serialisable."""
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError):  # fmt: skip
        text = str(value)
        if len(text) > 2000:
            text = text[:2000] + "…[truncated]"
        return text
