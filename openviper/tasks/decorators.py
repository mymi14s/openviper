"""Task decorator interface - wraps callables as background actors.

When ``settings.TASKS['enabled'] == 0``, ``.send()`` falls back to
synchronous execution in the caller's scope.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import typing as t

import dramatiq
import dramatiq.errors as dramatiq_errors

from openviper.conf import settings
from openviper.tasks.broker import get_broker
from openviper.tasks.logging import get_task_logger
from openviper.tasks.registry import Registry
from openviper.tasks.types import TaskMessageProxy

enqueue_logger = get_task_logger("openviper.tasks.enqueue")


def actor(
    fn: t.Callable[..., t.Any] | None = None,
    *,
    queue_name: str = "default",
    actor_name: str | None = None,
    max_retries: int = 3,
    min_backoff: int = 1000,
    max_backoff: int = 60000,
    time_limit: int = 600000,
) -> t.Callable[..., t.Any] | t.Callable[..., t.Any]:
    """Decorator that registers *fn* as a background task actor."""

    def decorator(func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        name = actor_name or func.__qualname__
        registry = Registry()
        registry.register_actor(name, func, queue_name=queue_name)

        @functools.wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            return func(*args, **kwargs)

        def send(*args: t.Any, **kwargs: t.Any) -> TaskMessageProxy:
            """Enqueue this actor for background execution."""
            return enqueue_task(name, args, kwargs, queue_name=queue_name)

        def send_with_options(
            *,
            args: tuple[t.Any, ...] = (),
            kwargs: dict[str, t.Any] | None = None,
            delay: int | None = None,
            queue: str | None = None,
        ) -> TaskMessageProxy:
            """Enqueue with explicit options (delay, queue override)."""
            return enqueue_task(
                name,
                tuple(args),
                kwargs or {},
                queue_name=queue or queue_name,
                delay=delay,
            )

        def message(*args: t.Any, **kwargs: t.Any) -> dict[str, t.Any]:
            """Build a serialisable message dict without enqueuing."""
            return {
                "actor_name": name,
                "queue_name": queue_name,
                "args": args,
                "kwargs": kwargs,
            }

        def get_result(
            proxy: TaskMessageProxy,
            *,
            block: bool = True,
            timeout: int | None = None,
        ) -> t.Any:
            """Retrieve the result for a previously enqueued message proxy.

            Delegates to :class:`TaskResultTracker` when a results
            backend is configured; otherwise raises
            :class:`ResultsBackendDisabledError`.
            """
            return proxy.get_result(block=block, timeout=timeout)

        wrapper.send = send
        wrapper.send_with_options = send_with_options
        wrapper.message = message
        wrapper.get_result = get_result
        wrapper.actor_name = name
        wrapper.queue_name = queue_name
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def enqueue_task(
    actor_name: str,
    args: tuple[t.Any, ...],
    kwargs: dict[str, t.Any],
    *,
    queue_name: str = "default",
    delay: int | None = None,
) -> TaskMessageProxy:
    """Dispatch a task message through the broker or execute inline."""
    cfg = settings.TASKS
    if not isinstance(cfg, dict):
        cfg = {}

    enabled = cfg.get("enabled", 1)

    if enabled == 0:
        registry = Registry()
        fn = registry.get_actor(actor_name)
        if inspect.iscoroutinefunction(fn):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(fn(*args, **kwargs))
            except RuntimeError:
                asyncio.run(fn(*args, **kwargs))
        else:
            fn(*args, **kwargs)
        return TaskMessageProxy(
            actor_name=actor_name,
            args=args,
            kwargs=kwargs,
            queue_name=queue_name,
        )

    try:
        broker = get_broker()

        # Register with Dramatiq broker if not yet declared.
        try:
            actor_obj = broker.get_actor(actor_name)
        except dramatiq_errors.ActorNotFound:
            registry = Registry()
            fn = registry.get_actor(actor_name)
            actor_obj = dramatiq.actor(
                actor_name=actor_name,
                queue_name=queue_name,
            )(fn)
            # broker.get_actor() will now succeed after dramatiq.actor() registration.

        msg = actor_obj.message(*args, **kwargs)
        if delay is not None:
            msg = msg.copy(options={"delay": delay})
        broker.enqueue(msg)
        return TaskMessageProxy(
            actor_name=actor_name,
            args=args,
            kwargs=kwargs,
            queue_name=queue_name,
            message_id=msg.message_id,
        )
    except Exception:
        enqueue_logger.exception("Failed to enqueue actor %s", actor_name)
        raise
