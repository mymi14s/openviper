"""Task testing utilities for OpenViper.

Provides :class:`TaskQueue` and :class:`EagerTaskRunner` for testing
code that enqueues background tasks without requiring a live worker.
"""

from __future__ import annotations

import typing as t
from collections import deque
from contextlib import contextmanager
from unittest.mock import patch

try:
    import dramatiq
except ImportError:
    dramatiq = None  # type: ignore[assignment]

try:
    from openviper.tasks.types import TaskMessageProxy
except ImportError:
    TaskMessageProxy = None  # type: ignore[assignment, misc]


def require_dramatiq(feature: str) -> None:
    """Raise RuntimeError if dramatiq is not installed."""
    if dramatiq is None:
        raise RuntimeError(
            f"dramatiq is required for {feature}. Install it with: pip install openviper[tasks]"
        )


class TaskQueue:
    """In-memory capture of task messages for test assertions.

    Usage::

        queue = TaskQueue()
        with queue.patch():
            my_task.send(1, 2)
        assert_task_queued(queue, "my_task")
    """

    def __init__(self) -> None:
        self.tasks: deque[dict[str, t.Any]] = deque()

    def add(self, actor_name: str, *args: t.Any, **kwargs: t.Any) -> None:
        """Record a task invocation."""
        self.tasks.append({"actor_name": actor_name, "args": args, "kwargs": kwargs})

    def has_task(self, actor_name: str) -> bool:
        """Return ``True`` if *actor_name* was enqueued."""
        return any(t["actor_name"] == actor_name for t in self.tasks)

    def clear(self) -> None:
        """Remove all recorded tasks."""
        self.tasks.clear()

    @contextmanager
    def patch(self) -> t.Iterator[TaskQueue]:
        """Context manager that intercepts ``actor.send()`` calls."""
        require_dramatiq("TaskQueue.patch()")

        def capturing_send(
            self_actor: dramatiq.Actor,
            *,
            args: tuple[t.Any, ...] = (),
            kwargs: dict[str, t.Any] | None = None,
            **opts: t.Any,
        ) -> object:
            self.add(self_actor.actor_name, *args, **(kwargs or {}))
            if TaskMessageProxy is not None:
                return TaskMessageProxy(
                    actor_name=self_actor.actor_name,
                    args=args,
                    kwargs=kwargs or {},
                    queue_name=getattr(self_actor, "queue_name", "default"),
                )
            return None

        with patch.object(dramatiq.Actor, "send_with_options", capturing_send):
            yield self


class EagerTaskRunner:
    """Execute task functions immediately in the test process.

    Usage::

        runner = EagerTaskRunner()
        result = await runner.run(my_task, 1, 2)
    """

    async def run(self, fn: t.Callable[..., t.Any], *args: t.Any, **kwargs: t.Any) -> t.Any:
        """Call *fn* with *args* and *kwargs* and return the result."""
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result


def assert_task_queued(queue: TaskQueue, actor_name: str) -> None:
    """Assert that *actor_name* appears in *queue*."""
    assert queue.has_task(actor_name), (
        f"Expected task '{actor_name}' to be queued, "
        f"but only found: {[t['actor_name'] for t in queue.tasks]}"
    )


def assert_task_count(queue: TaskQueue, count: int) -> None:
    """Assert that *queue* contains exactly *count* tasks."""
    actual = len(queue.tasks)
    assert actual == count, f"Expected {count} tasks, found {actual}"
