"""Task result retrieval via ``TaskResultTracker``.

Requires ``TASKS['backend_url']`` to be configured.
"""

from __future__ import annotations

import typing as t

import dramatiq.results

from openviper.tasks.broker import get_broker
from openviper.tasks.exceptions import ResultsBackendDisabledError

try:
    import dramatiq.results.backends
except ImportError:
    dramatiq.results.backends = None  # type: ignore[assignment]

if t.TYPE_CHECKING:
    from dramatiq import Broker

    from openviper.tasks.types import TaskMessageProxy


class TaskResultTracker:
    """Retrieve results for previously enqueued task messages."""

    def __init__(self, backend_url: str | None = None) -> None:
        self._backend_url = backend_url

    def get_result(
        self,
        proxy: TaskMessageProxy,
        *,
        block: bool = True,
        timeout: int | None = None,
    ) -> object:
        """Return the result of the task referenced by *proxy*.

        Raises :class:`ResultsBackendDisabledError` when no backend
        URL is configured.
        """
        if not self._backend_url:
            raise ResultsBackendDisabledError(
                "No results backend configured. "
                "Set TASKS['backend_url'] to enable result retrieval."
            )

        broker = get_broker()
        results = dramatiq.results.Results(backend=self.create_backend(broker))
        message = broker.get_actor(proxy.actor_name).message(*proxy._args, **proxy._kwargs)
        return results.get_result(message, block=block, timeout=timeout)

    def create_backend(self, broker: Broker) -> object:
        """Create a Dramatiq results backend from ``TASKS['backend_url']``."""
        if dramatiq.results.backends is None:
            raise ResultsBackendDisabledError(
                "dramatiq.results.backends is not available. "
                "Install with: pip install 'openviper[tasks-redis]'"
            )
        url = self._backend_url
        if url and url.startswith("redis://"):
            return dramatiq.results.backends.RedisBackend(url)
        raise ResultsBackendDisabledError(f"Unsupported results backend URL: {url!r}")
