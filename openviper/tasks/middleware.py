"""Dramatiq middleware for tracking task lifecycle events.

:class:`TaskTrackingMiddleware` hooks into every stage of a message's life
(enqueue → start → finish / fail) and persists the state to the
``openviper_task_results`` table via :mod:`openviper.tasks.results`.

Events are buffered in an in-process :class:`_EventBuffer` and flushed to
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
from datetime import datetime, timezone
from typing import Any

from dramatiq.middleware import Middleware

from openviper.tasks.results import batch_upsert_results

logger = logging.getLogger("openviper.tasks")

# Terminal statuses — trigger an immediate flush so results are visible ASAP.
_TERMINAL_STATUSES = frozenset({"success", "failure", "skipped", "dead"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Event value object
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class _TrackingEvent:
    """A single task state transition to be persisted."""

    message_id: str
    fields: dict[str, Any]
    terminal: bool  # if True the buffer is flushed immediately


# ---------------------------------------------------------------------------
# Event buffer — collects events and flushes in batches
# ---------------------------------------------------------------------------


class _EventBuffer:
    """Thread-safe buffer that batches task tracking events.

    Events are enqueued via :meth:`push`.  A flush is triggered when:

    * The event is terminal (success / failure / skipped / dead), or
    * The buffer size reaches ``flush_threshold``.

    Flushing calls :func:`~openviper.tasks.results.batch_upsert_results`
    with all buffered events in a single DB transaction.
    """

    def __init__(self, flush_threshold: int = 20) -> None:
        self._queue: deque[_TrackingEvent] = deque()
        self._lock = threading.Lock()
        self.flush_threshold = flush_threshold

    def push(self, event: _TrackingEvent) -> None:
        """Enqueue *event*; flush if terminal or threshold is reached."""
        with self._lock:
            self._queue.append(event)
            if event.terminal or len(self._queue) >= self.flush_threshold:
                events = list(self._queue)
                self._queue.clear()
            else:
                events = []
        if events:
            self._flush(events)

    def _flush(self, events: list[_TrackingEvent]) -> None:
        """Write *events* to the results table in a single transaction."""
        try:
            batch_upsert_results([(e.message_id, e.fields) for e in events])
        except Exception as exc:
            logger.debug("_EventBuffer._flush failed: %s", exc)


# Module-level singleton shared by all TaskTrackingMiddleware instances.
_event_buffer = _EventBuffer()


def reset_tracking_buffer() -> None:
    """Clear the event buffer.  Call in test teardown to prevent state leakage."""
    with _event_buffer._lock:
        _event_buffer._queue.clear()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class TaskTrackingMiddleware(Middleware):
    """Record task state transitions to the database via batched writes."""

    # ------------------------------------------------------------------
    # Enqueue side  (runs in the process that calls actor.send / .delay)
    # ------------------------------------------------------------------

    def before_enqueue(self, broker: Any, message: Any, delay: Any) -> None:
        try:
            _event_buffer.push(
                _TrackingEvent(
                    message_id=message.message_id,
                    fields={
                        "actor_name": message.actor_name,
                        "queue_name": message.queue_name,
                        "args": list(message.args),
                        "kwargs": dict(message.kwargs),
                        "status": "pending",
                        "enqueued_at": _now(),
                    },
                    terminal=False,
                )
            )
        except Exception as exc:
            logger.debug("TaskTracking.before_enqueue: %s", exc)

    # ------------------------------------------------------------------
    # Worker side  (runs inside the Dramatiq worker threads)
    # ------------------------------------------------------------------

    def before_process_message(self, broker: Any, message: Any) -> None:
        try:
            _event_buffer.push(
                _TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "running", "started_at": _now()},
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
            logger.debug("TaskTracking.before_process_message: %s", exc)

    def after_process_message(
        self,
        broker: Any,
        message: Any,
        *,
        result: Any = None,
        exception: Any = None,
    ) -> None:
        try:
            now = _now()
            if exception is None:
                _event_buffer.push(
                    _TrackingEvent(
                        message_id=message.message_id,
                        fields={
                            "status": "success",
                            "result": _serialise(result),
                            "completed_at": now,
                        },
                        terminal=True,
                    )
                )
                logger.info(
                    "[%s] Succeeded actor=%s",
                    message.message_id[:8],
                    message.actor_name,
                )
            else:
                _event_buffer.push(
                    _TrackingEvent(
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
            logger.debug("TaskTracking.after_process_message: %s", exc)

    def after_skip_message(self, broker: Any, message: Any) -> None:
        try:
            _event_buffer.push(
                _TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "skipped", "completed_at": _now()},
                    terminal=True,
                )
            )
        except Exception as exc:
            logger.debug("TaskTracking.after_skip_message: %s", exc)

    def after_nack(self, broker: Any, message: Any) -> None:
        """Called when a message is nacked (e.g. moved to the dead-letter queue)."""
        try:
            _event_buffer.push(
                _TrackingEvent(
                    message_id=message.message_id,
                    fields={"status": "dead", "completed_at": _now()},
                    terminal=True,
                )
            )
            logger.warning(
                "[%s] Dead-lettered  actor=%s",
                message.message_id[:8],
                message.actor_name,
            )
        except Exception as exc:
            logger.debug("TaskTracking.after_nack: %s", exc)


# ---------------------------------------------------------------------------
# Scheduler middleware — starts/stops the periodic scheduler with the worker
# ---------------------------------------------------------------------------


class SchedulerMiddleware(Middleware):
    """Start the periodic scheduler when the worker boots; stop it on shutdown.

    Attach this middleware to the broker so that ``@periodic`` tasks fire
    inside the worker process without requiring a separate beat process or
    parent-process discovery.  The ``after_worker_boot`` hook fires after
    all task modules have been imported and all ``@periodic`` registrations
    are in ``_pending``.
    """

    def after_worker_boot(self, broker: Any, worker: Any) -> None:
        from openviper.tasks.scheduler import start_scheduler

        try:
            start_scheduler()
        except Exception as exc:
            logger.warning("SchedulerMiddleware: could not start scheduler: %s", exc)

    def before_worker_shutdown(self, broker: Any, worker: Any) -> None:
        from openviper.tasks.scheduler import stop_scheduler

        try:
            stop_scheduler()
        except Exception as exc:
            logger.debug("SchedulerMiddleware: error stopping scheduler: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialise(value: Any) -> str | None:
    """Return a JSON string, or fall back to repr if not serialisable."""
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
