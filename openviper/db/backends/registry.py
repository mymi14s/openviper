"""Virtual backend registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.db.backends.sql import SQLVirtualBackend
from openviper.db.exceptions import VirtualBackendNotFoundError

if TYPE_CHECKING:
    from openviper.db.backends.base import VirtualBackend


class BackendRegistry:
    """Map virtual backend names to adapter instances."""

    def __init__(self) -> None:
        self.backends: dict[str, VirtualBackend] = {}

    def register(self, name: str, backend: VirtualBackend) -> None:
        """Register a backend adapter by name."""
        if not name:
            raise ValueError("Backend name cannot be empty.")
        self.backends[name] = backend

    def get(self, name: str) -> VirtualBackend:
        """Return the backend registered as *name*."""
        try:
            return self.backends[name]
        except KeyError as exc:
            raise VirtualBackendNotFoundError(
                f"Virtual backend '{name}' is not registered."
            ) from exc


backend_registry = BackendRegistry()
backend_registry.register("default", SQLVirtualBackend())
