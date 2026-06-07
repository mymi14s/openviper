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
from openviper.db.backends.features import DatabaseFeatures
from openviper.db.backends.introspection import DatabaseIntrospection
from openviper.db.utils import BoundedDict, cleanup_stale_locks_for_cache, get_per_loop_lock

logger = logging.getLogger(__name__)

_COMPILED_CACHE_MAX_SIZE: int = 2048


class SQLAlchemyFeatures(DatabaseFeatures):
    """Feature flags for the default SQLAlchemy backend."""

    def __init__(self, vendor: str) -> None:
        if vendor == "postgresql":
            self.supports_returning = True
            self.supports_partial_indexes = True
            self.supports_check_constraints = True
            self.supports_schema_comments = True
        elif vendor == "mysql":
            self.supports_returning = False
            self.supports_partial_indexes = False
            self.supports_check_constraints = True
            self.supports_schema_comments = False
        elif vendor == "sqlite":
            self.supports_returning = True
            self.supports_partial_indexes = False
            self.supports_check_constraints = True
            self.supports_schema_comments = False
        elif vendor == "mssql":
            self.supports_returning = True
            self.supports_partial_indexes = True
            self.supports_check_constraints = True
            self.supports_schema_comments = True
        elif vendor == "oracle":
            self.supports_returning = True
            self.supports_partial_indexes = False
            self.supports_check_constraints = True
            self.supports_schema_comments = True


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
        self.engine_lock_per_loop: dict[int, asyncio.Lock] = {}
        self.compiled_cache: BoundedDict = BoundedDict(_COMPILED_CACHE_MAX_SIZE)
        url = self.url
        self.vendor = self.operations.extract_vendor(url) if url else "unknown"

    def create_features(self) -> DatabaseFeatures:
        """Return feature flags based on the database vendor."""
        url = self.url
        vendor = self.operations.extract_vendor(url) if url else "unknown"
        return SQLAlchemyFeatures(vendor)

    def create_introspection(self) -> DatabaseIntrospection:
        """Return introspection using SQLAlchemy inspector."""
        return DatabaseIntrospection()

    async def create_engine(self) -> AsyncEngine:
        """Create and return the async SQLAlchemy engine for this alias.

        Uses double-checked locking to prevent two coroutines from
        both entering engine creation.
        """
        if self.engine is not None:
            return self.engine

        lock = cast("asyncio.Lock", get_per_loop_lock(self.engine_lock_per_loop))
        async with lock:
            if self.engine is not None:
                return self.engine
            self.engine = self.build_engine()
        return self.engine

    def build_engine(self) -> AsyncEngine:
        """Build the async engine from the configured URL."""
        url = self.url
        echo = bool(self.config.get("ECHO", False))
        async_url = self.operations.normalize_url(url)
        kwargs: dict[str, object] = {"echo": echo}
        is_memory = ":memory:" in async_url

        if is_memory:
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_pre_ping"] = True
            kwargs["pool_use_lifo"] = True
            for config_key, kwarg in (
                ("POOL_SIZE", "pool_size"),
                ("MAX_OVERFLOW", "max_overflow"),
                ("POOL_RECYCLE", "pool_recycle"),
                ("POOL_TIMEOUT", "pool_timeout"),
            ):
                value = self.config.get(config_key)
                if isinstance(value, (str, bytes, bytearray)) or hasattr(value, "__int__"):
                    kwargs[kwarg] = int(cast("str | bytes | bytearray | SupportsInt", value))

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

        if "sqlite" in async_url:

            @sa.event.listens_for(engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        return engine

    async def connect(self) -> AsyncConnection:
        """Return an async database connection for this alias."""
        engine = await self.create_engine()
        return engine.connect()

    async def disconnect(self) -> None:
        """Dispose the engine and clean up per-loop locks."""
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
