"""Router resolver that chains multiple DatabaseRouter instances."""

from __future__ import annotations

import importlib
import logging
from typing import cast

from openviper.conf import settings
from openviper.db.connections import DEFAULT_ALIAS
from openviper.db.exceptions import DatabaseRoutingError
from openviper.db.routing.base import DatabaseRouter
from openviper.db.routing.context import (
    current_db_alias,
    mark_write_used,
    read_from_primary,
)

logger = logging.getLogger(__name__)


class RouterResolver:
    """Resolve read/write/migration aliases using configured routers.

    Routers are checked in order.  The first non-``None`` result
    wins.  If all routers return ``None``, the default alias is
    used.
    """

    def __init__(self, routers: list[DatabaseRouter] | None = None) -> None:
        self.routers: list[DatabaseRouter] = routers or []

    async def resolve_read(self, model_class: type, **hints: object) -> str:
        """Return the database alias for a read operation.

        Checks the current transaction alias, read-your-writes
        flag, and then the router chain.
        """
        if read_from_primary.get():
            return current_db_alias.get()

        pinned = current_db_alias.get()
        if pinned != DEFAULT_ALIAS:
            return pinned

        alias = await self.query_routers("db_for_read", model_class, **hints)
        if alias is not None:
            return alias

        return DEFAULT_ALIAS

    async def resolve_write(self, model_class: type, **hints: object) -> str:
        """Return the database alias for a write operation.

        Marks the context as write-used for read-your-writes
        support.
        """
        mark_write_used()

        pinned = current_db_alias.get()
        if pinned != DEFAULT_ALIAS:
            return pinned

        alias = await self.query_routers("db_for_write", model_class, **hints)
        if alias is not None:
            return alias

        return DEFAULT_ALIAS

    async def resolve_relation(self, obj1: object, obj2: object, **hints: object) -> bool:
        """Return whether a relation between two objects is allowed."""
        for router in self.routers:
            result = await router.allow_relation(obj1, obj2, **hints)
            if result is not None:
                return result
        return True

    async def resolve_migrate(
        self,
        db_alias: str,
        model_class: type | None = None,
        **hints: object,
    ) -> bool:
        """Return whether migrations are allowed on *db_alias*."""
        for router in self.routers:
            result = await router.allow_migrate(db_alias, model_class, **hints)
            if result is not None:
                return result
        return db_alias == DEFAULT_ALIAS

    async def query_routers(
        self,
        method: str,
        model_class: type,
        **hints: object,
    ) -> str | None:
        """Query each router for *method* and return the first non-None alias."""
        for router in self.routers:
            handler = getattr(router, method, None)
            if handler is None:
                continue
            result = await handler(model_class, **hints)
            if result is not None:
                if not isinstance(result, str):
                    raise DatabaseRoutingError(
                        f"Router {type(router).__name__}.{method} returned "
                        f"{type(result).__name__}, expected str or None."
                    )
                return result
        return None


class DefaultRouterResolver(RouterResolver):
    """Router resolver that loads routers from settings on first use.

    Reads ``DATABASE_ROUTERS`` from settings and instantiates
    each router class lazily.
    """

    def __init__(self) -> None:
        super().__init__()
        self.loaded: bool = False

    def ensure_loaded(self) -> None:
        """Load routers from settings if not yet loaded."""
        if self.loaded:
            return
        self.loaded = True

        router_paths = getattr(settings, "DATABASE_ROUTERS", [])
        if not router_paths:
            return

        for path in router_paths:
            if isinstance(path, str):
                router = self.import_router(path)
                if router is not None:
                    self.routers.append(router)
            elif isinstance(path, DatabaseRouter):
                self.routers.append(path)

    def import_router(self, import_path: str) -> DatabaseRouter | None:
        """Import and instantiate a router class from a dotted path."""
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            router_cls = getattr(module, class_name)
            return cast("DatabaseRouter", router_cls())
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "Could not import database router '%s': %s.",
                import_path,
                exc,
            )
            return None

    async def resolve_read(self, model_class: type, **hints: object) -> str:
        self.ensure_loaded()
        return await super().resolve_read(model_class, **hints)

    async def resolve_write(self, model_class: type, **hints: object) -> str:
        self.ensure_loaded()
        return await super().resolve_write(model_class, **hints)

    async def resolve_relation(self, obj1: object, obj2: object, **hints: object) -> bool:
        self.ensure_loaded()
        return await super().resolve_relation(obj1, obj2, **hints)

    async def resolve_migrate(
        self,
        db_alias: str,
        model_class: type | None = None,
        **hints: object,
    ) -> bool:
        self.ensure_loaded()
        return await super().resolve_migrate(db_alias, model_class, **hints)


resolver = DefaultRouterResolver()
