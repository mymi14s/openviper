"""Type definitions for the tasks subsystem."""

from __future__ import annotations

import typing as t

from openviper.conf import settings
from openviper.tasks.exceptions import ResultsBackendDisabledError
from openviper.tasks.results import TaskResultTracker


class TaskMessageProxy:
    """Thin wrapper returned by ``actor.send()`` and ``actor.send_with_options()``.

    Carries the message payload and provides ``.get_result()`` when a
    results backend is configured.
    """

    __slots__ = ("_message_id", "_actor_name", "_args", "_kwargs", "_queue_name")

    def __init__(
        self,
        actor_name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        queue_name: str = "default",
        message_id: str | None = None,
    ) -> None:
        self._actor_name = actor_name
        self._args = args
        self._kwargs = kwargs
        self._queue_name = queue_name
        self._message_id = message_id or ""

    @property
    def actor_name(self) -> str:
        return self._actor_name

    @property
    def queue_name(self) -> str:
        return self._queue_name

    @property
    def message_id(self) -> str:
        return self._message_id

    def get_result(
        self,
        *,
        block: bool = True,
        timeout: int | None = None,
    ) -> t.Any:
        """Retrieve the result of this task message.

        Raises :class:`ResultsBackendDisabledError` when no backend
        is configured.
        """
        try:
            cfg = settings.TASKS if isinstance(settings.TASKS, dict) else {}
        except Exception:
            cfg = {}

        backend_url = cfg.get("backend_url", "")
        if not backend_url:
            raise ResultsBackendDisabledError(
                "No results backend configured. "
                "Set TASKS['backend_url'] to enable result retrieval."
            )

        tracker = TaskResultTracker(backend_url=str(backend_url))
        return tracker.get_result(self, block=block, timeout=timeout)
