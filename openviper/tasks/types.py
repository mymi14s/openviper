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

    __slots__ = ("message_id_value", "actor_name_value", "args", "kwargs", "queue_name_value")

    def __init__(
        self,
        actor_name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        queue_name: str = "default",
        message_id: str | None = None,
    ) -> None:
        self.actor_name_value = actor_name
        self.args = args
        self.kwargs = kwargs
        self.queue_name_value = queue_name
        self.message_id_value = message_id or ""

    @property
    def actor_name(self) -> str:
        return self.actor_name_value

    @property
    def queue_name(self) -> str:
        return self.queue_name_value

    @property
    def message_id(self) -> str:
        return self.message_id_value

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

        backend_url_raw = cfg.get("backend_url") or ""
        if not backend_url_raw:
            raise ResultsBackendDisabledError(
                "No results backend configured. "
                "Set TASKS['backend_url'] to enable result retrieval."
            )

        tracker = TaskResultTracker(backend_url=t.cast("str", backend_url_raw))
        return tracker.get_result(self, block=block, timeout=timeout)
