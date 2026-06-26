"""Database patch system for one-time data migrations.

Provides the ``@db_patch`` decorator for registering data migration
functions that run during ``migrate`` and are tracked to ensure
each runs exactly once.
"""

from __future__ import annotations

import typing as t
from typing import overload

if t.TYPE_CHECKING:
    import collections.abc as c

__all__ = [
    "db_patch",
    "PatchEntry",
    "PatchRegistry",
    "get_registry",
    "reset_registry",
]


class PatchEntry:
    """Concrete patch entry stored in the registry."""

    __slots__ = ("app", "module", "name", "func", "order", "post_migrate")

    def __init__(
        self,
        app: str,
        module: str,
        name: str,
        func: c.Callable[[], t.Awaitable[None]],
        order: int,
        post_migrate: bool,
    ) -> None:
        self.app = app
        self.module = module
        self.name = name
        self.func = func
        self.order = order
        self.post_migrate = post_migrate

    def __repr__(self) -> str:
        return (
            f"PatchEntry(app={self.app!r}, module={self.module!r},"
            f" name={self.name!r}, order={self.order},"
            f" post_migrate={self.post_migrate})"
        )


class PatchRegistry:
    """Global registry for ``@db_patch`` decorated functions."""

    def __init__(self) -> None:
        self._patches: list[PatchEntry] = []

    def register(self, entry: PatchEntry) -> None:
        """Add a patch entry to the registry."""
        self._patches.append(entry)

    def get_all(self) -> list[PatchEntry]:
        """Return all registered patches."""
        return list(self._patches)

    def get_sorted(self, post_migrate: bool = True) -> list[PatchEntry]:
        """Return patches filtered by phase, preserving registration order."""
        return [p for p in self._patches if p.post_migrate == post_migrate]

    def clear(self) -> None:
        """Remove all registered patches."""
        self._patches.clear()


_registry: PatchRegistry = PatchRegistry()


def get_registry() -> PatchRegistry:
    """Return the global patch registry."""
    return _registry


def reset_registry() -> None:
    """Clear the global registry. Intended for test isolation."""
    _registry.clear()


@overload
def db_patch(
    func: c.Callable[[], t.Awaitable[None]],
) -> c.Callable[[], t.Awaitable[None]]: ...


@overload
def db_patch(
    func: None = None,
    *,
    order: int = 0,
    post_migrate: bool = True,
) -> t.Callable[
    [c.Callable[[], t.Awaitable[None]]],
    c.Callable[[], t.Awaitable[None]],
]: ...


def db_patch(
    func: c.Callable[[], t.Awaitable[None]] | None = None,
    *,
    order: int = 0,
    post_migrate: bool = True,
) -> (
    c.Callable[[], t.Awaitable[None]]
    | t.Callable[
        [c.Callable[[], t.Awaitable[None]]],
        c.Callable[[], t.Awaitable[None]],
    ]
):
    """Register a function as a database patch.

    Args:
        func: The async function to register. When used without
            parentheses (``@db_patch``), this is the function directly.
        order: Deprecated. Patches execute in registration order (FIFO)
            within a phase; this value is ignored.
        post_migrate: If True (default), runs after schema sync.
            If False, runs before schema sync.

    Usage::

        @db_patch
        async def backfill_status():
            ...

        @db_patch(post_migrate=False)
        async def read_old_fields():
            ...

        @db_patch(order=2)
        async def cleanup_permissions():
            ...
    """

    def decorator(
        fn: c.Callable[[], t.Awaitable[None]],
    ) -> c.Callable[[], t.Awaitable[None]]:
        module_name = fn.__module__
        parts = module_name.split(".")
        app = parts[0] if parts else ""

        entry = PatchEntry(
            app=app,
            module=module_name,
            name=fn.__name__,
            func=fn,
            order=order,
            post_migrate=post_migrate,
        )
        _registry.register(entry)
        return fn

    if func is not None:
        return decorator(func)
    return decorator
