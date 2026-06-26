"""Thread-safe singleton registry for task actors and periodic schedules.

Protects against duplicate names and circular discovery loops.
"""

from __future__ import annotations

import threading
import typing as t


class Registry:
    """Thread-safe registry of task actors and periodic schedules."""

    instance: Registry | None = None
    lock = threading.Lock()

    actors_store: dict[str, t.Callable[..., t.Any]]
    actor_queues_store: dict[str, str]
    actor_options_store: dict[str, dict[str, t.Any]]
    periodic_store: dict[str, dict[str, t.Any]]
    discovered_apps: set[str]

    def __new__(cls) -> Registry:
        if cls.instance is None:
            with cls.lock:
                if cls.instance is None:
                    obj = super().__new__(cls)
                    obj.actors_store = {}
                    obj.actor_queues_store = {}
                    obj.actor_options_store = {}
                    obj.periodic_store = {}
                    obj.discovered_apps = set()
                    cls.instance = obj
        return cls.instance

    def register_actor(
        self,
        name: str,
        fn: t.Callable[..., t.Any],
        *,
        queue_name: str = "default",
        options: dict[str, t.Any] | None = None,
    ) -> None:
        """Register *fn* under *name*. Raises ValueError if already registered."""
        if name in self.actors_store:
            raise ValueError(f"Actor '{name}' is already registered")
        self.actors_store[name] = fn
        self.actor_queues_store[name] = queue_name
        self.actor_options_store[name] = options or {}

    def get_actor_options(self, name: str) -> dict[str, t.Any]:
        """Return the dramatiq actor options for the actor *name*."""
        return self.actor_options_store.get(name, {})

    def get_actor(self, name: str) -> t.Callable[..., t.Any]:
        """Return the callable registered under *name*."""
        try:
            return self.actors_store[name]
        except KeyError:
            raise KeyError(f"Actor '{name}' not found in registry") from None

    def get_actor_queue(self, name: str) -> str:
        """Return the queue name for the actor registered under *name*."""
        return self.actor_queues_store.get(name, "default")

    @property
    def actors(self) -> dict[str, t.Callable[..., t.Any]]:
        """Snapshot of all registered actors."""
        return dict(self.actors_store)

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
        if name in self.periodic_store:
            raise ValueError(f"Periodic job '{name}' is already registered")
        self.periodic_store[name] = {
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
        return dict(self.periodic_store)

    def mark_discovered(self, app_label: str) -> None:
        """Record that *app_label* has been scanned for tasks."""
        self.discovered_apps.add(app_label)

    def is_discovered(self, app_label: str) -> bool:
        """Return whether *app_label* has already been scanned."""
        return app_label in self.discovered_apps

    def clear(self) -> None:
        """Remove all registrations. Intended for test teardown."""
        self.actors_store.clear()
        self.actor_queues_store.clear()
        self.periodic_store.clear()
        self.discovered_apps.clear()
