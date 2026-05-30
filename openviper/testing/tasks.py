"""Background task testing helpers."""

import dataclasses
import typing as t
from collections.abc import Callable


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedTask:
    """Captured background task."""

    name: str
    args: tuple[object, ...]
    kwargs: dict[str, object]


class TaskQueue:
    """In-memory queue for deterministic task assertions."""

    def __init__(self) -> None:
        self.tasks: list[QueuedTask] = []

    def add(self, name: str, *args: object, **kwargs: object) -> None:
        self.tasks.append(QueuedTask(name=name, args=args, kwargs=kwargs))

    def has_task(self, name: str) -> bool:
        return any(task.name == name for task in self.tasks)

    def clear(self) -> None:
        self.tasks.clear()


def assert_task_queued(queue: TaskQueue, name: str) -> None:
    assert queue.has_task(name), f"Expected task {name!r} to be queued."


def assert_task_count(queue: TaskQueue, expected: int) -> None:
    actual = len(queue.tasks)
    assert actual == expected, f"Expected {expected} queued task(s), got {actual}."


class EagerTaskRunner:
    """Execute async or sync callables immediately in tests."""

    async def run(self, task: object, *args: object, **kwargs: object) -> object:
        callable_task = t.cast("Callable[..., object]", task)
        result = callable_task(*args, **kwargs)
        if hasattr(result, "__await__"):
            return await t.cast("t.Awaitable[object]", result)
        return result
