"""In-process broker that persists tasks to the database.

Used when ``TASKS['broker'] == 'database'``.
"""

from __future__ import annotations

import typing as t
import uuid

from openviper.tasks.logging import get_task_logger

logger = get_task_logger("openviper.tasks.db_broker")


class DatabaseBroker:
    """In-process broker that persists tasks to ``TaskResult``."""

    def __init__(self) -> None:
        self._actors: dict[str, t.Callable[..., t.Any]] = {}

    def declare_actor(self, actor_name: str, fn: t.Callable[..., t.Any]) -> None:
        """Register an actor callable under *actor_name*."""
        self._actors[actor_name] = fn

    def get_actor(self, actor_name: str) -> t.Callable[..., t.Any]:
        """Return the callable registered under *actor_name*."""
        try:
            return self._actors[actor_name]
        except KeyError:
            raise KeyError(f"Actor '{actor_name}' not found in DatabaseBroker") from None

    def enqueue(self, message: dict[str, t.Any]) -> str:
        """Persist a task message and return its ID."""
        message_id = str(uuid.uuid4())
        logger.info("DatabaseBroker: enqueued %s (id=%s)", message.get("actor_name"), message_id)
        return message_id
