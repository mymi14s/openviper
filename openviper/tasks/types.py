"""Shared structural types for the task subsystem."""

from __future__ import annotations

import typing as t
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence

from sqlalchemy.engine import Connection, Engine, Row

type TaskValue = object
type TaskFields = dict[str, TaskValue]
type TaskResultRow = dict[str, TaskValue]
type TaskArgs = tuple[TaskValue, ...]
type TaskKwargs = dict[str, TaskValue]
type TaskCallable = Callable[..., TaskValue]
type UpsertFunction = Callable[[Connection, str, TaskFields], None]
type SqlRow = Row[tuple[TaskValue, ...]]


class ActorProtocol(t.Protocol):
    """Dramatiq actor operations used by the scheduler."""

    actor_name: str

    def send(self, *args: TaskValue, **kwargs: TaskValue) -> object: ...


class DelayActorProtocol(ActorProtocol, t.Protocol):
    """Actor with the optional delay alias installed by ``task``."""

    delay: Callable[..., object]


type TaskDecorator = Callable[[TaskCallable], ActorProtocol]


class BrokerProtocol(t.Protocol):
    """Broker operations used by task setup and workers."""

    def add_middleware(self, middleware: object) -> None: ...

    def get_declared_queues(self) -> set[str]: ...

    def close(self) -> None: ...


class SettingsProtocol(t.Protocol):
    """Settings values consumed by the task subsystem."""

    TASKS: Mapping[str, object]
    DATABASE_URL: str
    LOG_LEVEL: str
    LOG_FORMAT: str


class TaskMessageProtocol(t.Protocol):
    """Dramatiq message fields consumed by middleware."""

    message_id: str
    actor_name: str
    queue_name: str
    args: Sequence[TaskValue]
    kwargs: Mapping[str, TaskValue]
    options: MutableMapping[str, TaskValue]


class TaskMessageProxyProtocol(t.Protocol):
    """Message proxy fields used by the database broker."""

    options: MutableMapping[str, TaskValue]


class UpsertBuilderProtocol(t.Protocol):
    """Factory for dialect-specific SQLAlchemy insert statements."""

    def __call__(self, table: object) -> object: ...


class SchedulerEventProtocol(t.Protocol):
    """Thread event operations required by the scheduler loop."""

    def clear(self) -> None: ...

    def set(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class WorkerProtocol(t.Protocol):
    """Worker lifecycle surface used by the runner."""

    broker: BrokerProtocol

    def start(self) -> None: ...

    def stop(self, timeout: int) -> None: ...


class QueryResultProtocol(t.Protocol):
    """SQL execution result methods used by result queries."""

    rowcount: int | None


class EngineHolder(t.Protocol):
    """Engine lifecycle operations used during test and worker teardown."""

    def dispose(self) -> None: ...


__all__ = [
    "ActorProtocol",
    "BrokerProtocol",
    "DelayActorProtocol",
    "Engine",
    "EngineHolder",
    "Iterable",
    "QueryResultProtocol",
    "SettingsProtocol",
    "SqlRow",
    "TaskArgs",
    "TaskCallable",
    "TaskDecorator",
    "TaskFields",
    "TaskKwargs",
    "TaskMessageProtocol",
    "TaskMessageProxyProtocol",
    "TaskResultRow",
    "TaskValue",
    "UpsertFunction",
    "WorkerProtocol",
]
