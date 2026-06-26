"""Default SQLAlchemy database backend wrapping existing OpenViper behavior."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any, NoReturn, SupportsInt, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from openviper.db.backends.database import DatabaseBackend
from openviper.db.backends.features import DatabaseFeatures, get_features_for_vendor
from openviper.db.backends.introspection import DatabaseIntrospection
from openviper.db.constants import COMPILED_CACHE_MAX_SIZE
from openviper.db.dialects import get_dialect
from openviper.db.utils import (
    BoundedDict,
    cleanup_stale_locks_for_cache,
    dispose_per_loop_engines,
    get_per_loop_lock,
    get_running_loop_or_none,
)

logger = logging.getLogger(__name__)


class DefaultDatabaseBackend(DatabaseBackend):
    """Default database backend using SQLAlchemy async engine.

    Wraps the existing OpenViper connection and execution behaviour.
    When ``BACKEND`` is omitted from a ``DATABASES`` alias config,
    this backend is used automatically.
    """

    vendor: str = "sqlalchemy"
    display_name: str = "SQLAlchemy"

    def __init__(self, alias: str, config: Mapping[str, Any]) -> None:
        super().__init__(alias, config)
        self.engine: AsyncEngine | None = None
        self.engines_per_loop: dict[int, AsyncEngine] = {}
        self.engine_lock_per_loop: dict[int, asyncio.Lock] = {}
        self.compiled_cache: BoundedDict = BoundedDict(COMPILED_CACHE_MAX_SIZE)
        url = self.url
        self.vendor = self.operations.extract_vendor(url) if url else "unknown"

    def create_features(self) -> DatabaseFeatures:
        """Return feature flags based on the database vendor."""
        url = self.url
        vendor = self.operations.extract_vendor(url) if url else "unknown"
        return get_features_for_vendor(vendor)

    def create_introspection(self) -> DatabaseIntrospection:
        """Return introspection using SQLAlchemy inspector."""
        return DatabaseIntrospection()

    async def create_engine(self) -> AsyncEngine:
        """
        Create and return the async SQLAlchemy engine for this alias.

        """
        loop = get_running_loop_or_none()

        if loop is not None:
            loop_id = id(loop)
            cached = self.engines_per_loop.get(loop_id)
            if cached is not None:
                return cached
        elif self.engine is not None:
            return self.engine

        lock = cast("asyncio.Lock", get_per_loop_lock(self.engine_lock_per_loop))
        async with lock:
            if loop is not None:
                loop_id = id(loop)
                cached = self.engines_per_loop.get(loop_id)
                if cached is not None:
                    return cached
            elif self.engine is not None:
                return self.engine
            new_engine = self.build_engine()
            if loop is not None:
                self.engines_per_loop[id(loop)] = new_engine
            else:
                self.engine = new_engine
        return new_engine

    def build_engine(self) -> AsyncEngine:
        """Build the async engine from the configured URL.

        Dialect-specific configuration (connect args, pragmas, JSON
        serializers) is delegated to the resolved :class:`Dialect`
        instance, which is cached for the process lifecycle.
        """
        url = self.url
        echo = bool(self.get_option("ECHO", False))
        dialect = get_dialect()
        async_url = dialect.normalize_url(url)
        kwargs: dict[str, object] = {"echo": echo}
        is_memory = ":memory:" in async_url

        if is_memory:
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            uses_aiomysql = "aiomysql" in async_url
            kwargs["pool_pre_ping"] = not uses_aiomysql
            kwargs["pool_use_lifo"] = True
            for config_key, kwarg in (
                ("POOL_SIZE", "pool_size"),
                ("MAX_OVERFLOW", "max_overflow"),
                ("POOL_RECYCLE", "pool_recycle"),
                ("POOL_TIMEOUT", "pool_timeout"),
            ):
                value = self.get_option(config_key)
                if isinstance(value, (str, bytes, bytearray)) or hasattr(value, "__int__"):
                    kwargs[kwarg] = int(cast("str | bytes | bytearray | SupportsInt", value))

        dialect_kwargs = dialect.get_engine_kwargs(async_url, is_memory)
        for key, val in dialect_kwargs.items():
            if key == "connect_args":
                existing = kwargs.get("connect_args", {})
                if isinstance(existing, dict):
                    existing.update(val)
                    kwargs["connect_args"] = existing
                else:
                    kwargs["connect_args"] = val
            elif key == "poolclass":
                kwargs["poolclass"] = val
            else:
                kwargs[key] = val

        try:
            engine = create_async_engine(
                async_url,
                execution_options={"compiled_cache": self.compiled_cache},
                **kwargs,
            )
        except (ModuleNotFoundError, ImportError) as exc:
            if "asyncpg" in async_url or "aiomysql" in async_url:
                return cast(
                    "AsyncEngine",
                    MissingDriverAsyncEngine(async_url, echo, exc.name or ""),
                )
            raise

        dialect.configure_engine(engine, async_url)

        return engine

    async def connect(self) -> AsyncConnection:
        """Return an async database connection for this alias."""
        engine = await self.create_engine()
        return engine.connect()

    async def disconnect(self) -> None:
        """Dispose all engines and clean up per-loop locks."""
        await dispose_per_loop_engines(self.engines_per_loop)
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
        cleanup_stale_locks_for_cache(self.engine_lock_per_loop)

    async def execute(
        self,
        statement: sa.Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        """Execute a SQLAlchemy statement through the execution hooks."""
        engine = await self.create_engine()
        async with engine.connect() as conn:
            return await self.execution.execute(conn, statement, parameters)

    def transaction(self, using: str | None = None) -> Any:
        """Return a transaction context manager for this alias.

        *using* is accepted for API compatibility but the default
        backend always uses its own engine.
        """
        return self.atomic()

    @asynccontextmanager
    async def atomic(self) -> AsyncGenerator[AsyncConnection]:
        """Async context manager wrapping ORM operations in a transaction."""
        engine = await self.create_engine()
        async with engine.begin() as conn:
            yield conn

    async def init_db(self, drop_first: bool = False) -> None:
        """Create all registered tables.  Optionally drop them first."""
        engine = await self.create_engine()
        metadata = self.get_metadata()

        if drop_first:
            if "sqlite" in str(engine.url):
                async with engine.begin() as conn:
                    await conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
                    await conn.run_sync(metadata.drop_all)
                    await conn.execute(sa.text("PRAGMA foreign_keys=ON"))
            else:
                async with engine.begin() as conn:
                    await conn.run_sync(metadata.drop_all)

        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)


class MissingDriverAsyncEngine:
    """Minimal async-engine stand-in when optional DB drivers are absent."""

    def __init__(self, url: str, echo: bool, missing_driver: str) -> None:
        self.url = sa.engine.make_url(url)
        self.echo = echo
        self.missing_driver = missing_driver

    async def dispose(self) -> None:
        return None

    def connect(self) -> NoReturn:
        raise ModuleNotFoundError(
            f"No module named {self.missing_driver!r}; install the database driver "
            f"required for {self.url.drivername!r}."
        )
