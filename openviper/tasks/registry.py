"""Thread-safe singleton registry for task actors and periodic schedules.

Protects against duplicate names and circular discovery loops.
"""

from __future__ import annotations

import threading
import typing as t


class Registry:
    """Thread-safe registry of task actors and periodic schedules."""

    _instance: Registry | None = None
    _lock = threading.Lock()

    _actors: dict[str, t.Callable[..., t.Any]]
    _actor_queues: dict[str, str]
    _periodic: dict[str, dict[str, t.Any]]
    _discovered_apps: set[str]

    def __new__(cls) -> Registry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._actors = {}
                    instance._actor_queues = {}
                    instance._periodic = {}
                    instance._discovered_apps = set()
                    cls._instance = instance
        return cls._instance

    def register_actor(
        self,
        name: str,
        fn: t.Callable[..., t.Any],
        *,
        queue_name: str = "default",
    ) -> None:
        """Register *fn* under *name*. Raises on duplicate."""
        if name in self._actors:
            raise ValueError(f"Actor '{name}' is already registered")
        self._actors[name] = fn
        self._actor_queues[name] = queue_name

    def get_actor(self, name: str) -> t.Callable[..., t.Any]:
        """Return the callable registered under *name*."""
        try:
            return self._actors[name]
        except KeyError:
            raise KeyError(f"Actor '{name}' not found in registry") from None

    def get_actor_queue(self, name: str) -> str:
        """Return the queue name for the actor registered under *name*."""
        return self._actor_queues.get(name, "default")

    @property
    def actors(self) -> dict[str, t.Callable[..., t.Any]]:
        """Snapshot of all registered actors."""
        return dict(self._actors)

    def register_periodic(
        self,
        name: str,
        schedule: str,
        *,
        cron: str | None = None,
        every: str | int | None = None,
        startup: bool = False,
        retries: int = 3,
        app_label: str | None = None,
    ) -> None:
        """Register a periodic schedule entry under *name*."""
        if name in self._periodic:
            raise ValueError(f"Periodic job '{name}' is already registered")
        self._periodic[name] = {
            "name": name,
            "schedule": schedule,
            "cron": cron,
            "every": every,
            "startup": startup,
            "retries": retries,
            "app_label": app_label or "",
        }

    @property
    def periodic_jobs(self) -> dict[str, dict[str, t.Any]]:
        """Snapshot of all registered periodic schedules."""
        return dict(self._periodic)

    def mark_discovered(self, app_label: str) -> None:
        """Record that *app_label* has been scanned for tasks."""
        self._discovered_apps.add(app_label)

    def is_discovered(self, app_label: str) -> bool:
        """Return whether *app_label* has already been scanned."""
        return app_label in self._discovered_apps

    def clear(self) -> None:
        """Remove all registrations. Intended for test teardown."""
        self._actors.clear()
        self._actor_queues.clear()
        self._periodic.clear()
        self._discovered_apps.clear()
