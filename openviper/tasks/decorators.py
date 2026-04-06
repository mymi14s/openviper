"""``@task`` decorator — registers a function as a Dramatiq actor.

Usage::

    from openviper.tasks import task

    @task(queue_name="emails", max_retries=5)
    async def send_welcome(user_id: int) -> None:
        ...

    # Enqueue
    send_welcome.send(42)       # fire-and-forget
    send_welcome.delay(42)      # alias for .send()
    send_welcome.send_with_options(args=(42,), delay=5_000)  # 5-second delay

    # Explicit actor name (avoids collisions when two apps share a function name)
    @task(actor_name="payments.charge")
    async def charge(order_id: int) -> None:
        ...

Async functions are handled transparently by Dramatiq's built-in
:class:`~dramatiq.middleware.asyncio.AsyncIO` middleware, which the broker
attaches in :mod:`openviper.tasks.broker`.  No manual event-loop wiring is
needed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import dramatiq

import openviper.tasks.broker as _broker_module

logger = logging.getLogger("openviper.tasks")


def task(
    queue_name: str = "default",
    priority: int = 0,
    max_retries: int = 3,
    min_backoff: int = 15_000,
    max_backoff: int = 300_000,
    time_limit: int | None = None,
    actor_name: str | None = None,
) -> Callable[..., Any]:
    """Decorator that registers a callable as a Dramatiq background task.

    Args:
        queue_name:  Queue to route the message to.  Workers can be
                     restricted to specific queues with ``--queues``.
        priority:    Message priority within the queue (higher = processed
                     sooner when the queue is longer than the concurrency).
        max_retries: Maximum number of automatic retries on failure.
                     Set to ``0`` to disable retries.
        min_backoff: Minimum retry back-off in milliseconds.
        max_backoff: Maximum retry back-off in milliseconds.
        time_limit:  Hard execution timeout in milliseconds, or ``None``
                     for no limit.
        actor_name:  Explicit Dramatiq actor name.  Defaults to the
                     function's own ``__name__`` (e.g. ``"moderate"``).
                     Override this when two apps define functions with the
                     same name to avoid registration collisions.

    Returns:
        A decorated Dramatiq :class:`~dramatiq.Actor` with an extra
        ``.delay()`` alias on ``.send()``.
    """

    def decorator(fn: Callable[..., Any]) -> Any:
        _broker_module.get_broker()

        resolved_name = actor_name if actor_name is not None else fn.__name__

        actor_kwargs: dict[str, Any] = {
            "actor_name": resolved_name,
            "queue_name": queue_name,
            "priority": priority,
            "max_retries": max_retries,
            "min_backoff": min_backoff,
            "max_backoff": max_backoff,
        }
        if time_limit is not None:
            actor_kwargs["time_limit"] = time_limit

        actor = dramatiq.actor(fn, **actor_kwargs)

        # Convenience alias so both .send() and .delay() work.
        actor.delay = actor.send  # type: ignore[attr-defined]

        logger.debug(
            "Registered task %r  actor_name=%r  queue=%s  max_retries=%d",
            fn.__qualname__,
            resolved_name,
            queue_name,
            max_retries,
        )
        return actor

    return decorator
