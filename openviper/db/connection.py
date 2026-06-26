"""Database connection management using SQLAlchemy async engine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, cast
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from openviper.conf import settings
from openviper.db.backends.operations import DatabaseOperations
from openviper.db.backends.sqlalchemy import MissingDriverAsyncEngine
from openviper.db.connections import connections
from openviper.db.constants import COMPILED_CACHE_MAX_SIZE
from openviper.db.dialects import resolve_dialect_by_vendor
from openviper.db.exceptions import DatabaseReadOnlyError
from openviper.db.model_registry import rebuild_all_tables
from openviper.db.routing.context import current_db_alias, reset_current_alias, set_current_alias
from openviper.db.shared_metadata import metadata
from openviper.db.utils import (
    BoundedDict,
    cleanup_stale_locks_for_cache,
    dispose_per_loop_engines,
    get_database_option,
    get_default_database_url,
    get_per_loop_lock,
    get_running_loop_or_none,
    validate_pool_config,
)

logger = logging.getLogger(__name__)


_engine: AsyncEngine | None = None
_engines_per_loop: dict[int, AsyncEngine] = {}

# Per-request connection for reuse across multiple ORM calls.
_request_conn: ContextVar[AsyncConnection | None] = ContextVar("_request_conn", default=None)
_transaction_alias: ContextVar[str | None] = ContextVar("_transaction_alias", default=None)
_transaction_writes_allowed: ContextVar[bool] = ContextVar(
    "_transaction_writes_allowed",
    default=True,
)

_compiled_cache: BoundedDict = BoundedDict(COMPILED_CACHE_MAX_SIZE)

# Per-event-loop engine lock storage to avoid cross-loop errors.
# Cleaned up when the engine is disposed to prevent memory leaks from
# stale event loops in long-running processes (test runners, workers).
_engine_lock_per_loop: dict[int, asyncio.Lock] = {}


def cleanup_stale_locks() -> None:
    """Remove lock entries for event loops that are no longer running.

    Called during engine disposal to prevent unbounded growth of the
    per-loop lock dict in processes that create and destroy event loops.
    """
    cleanup_stale_locks_for_cache(_engine_lock_per_loop)


def get_engine_lock() -> asyncio.Lock:
    """Return a per-event-loop engine lock, creating lazily."""
    return get_per_loop_lock(_engine_lock_per_loop)


def get_metadata() -> sa.MetaData:
    return metadata


async def get_engine() -> AsyncEngine:
    """Return (or lazily create) the shared async engine.

    Engines are cached per event loop to prevent cross-loop
    ``RuntimeError: Future attached to a different loop`` errors in
    multi-threaded workers where coroutines may run on different loops.
    """
    global _engine

    loop = get_running_loop_or_none()

    if loop is not None:
        loop_id = id(loop)
        cached = _engines_per_loop.get(loop_id)
        if cached is not None:
            return cached
    elif _engine is not None:
        return _engine

    lock = get_engine_lock()
    async with lock:
        if loop is not None:
            loop_id = id(loop)
            cached = _engines_per_loop.get(loop_id)
            if cached is not None:
                return cached
        elif _engine is not None:
            return _engine

        new_engine = create_engine(
            get_default_database_url(settings),
            cast("bool", get_database_option(settings, "ECHO", False)),
        )
        if loop is not None:
            _engines_per_loop[id(loop)] = new_engine
        else:
            _engine = new_engine

    return new_engine


async def dispose_engine() -> None:
    """Dispose all shared engines and release pooled connections."""
    global _engine
    await dispose_per_loop_engines(_engines_per_loop)
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    cleanup_stale_locks()


_operations = DatabaseOperations()


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL.

    Dialect-specific configuration (connect args, pragmas, JSON
    serializers) is delegated to the resolved :class:`Dialect` instance.
    """
    if not url or not url.strip():
        raise ValueError(
            "Database URL is empty or not set. "
            "Configure DATABASES['default']['OPTIONS']['URL'] in your "
            "project settings (e.g. settings.py). "
            "Example: 'postgresql+asyncpg://user:password@localhost/dbname'"
        )

    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0]
    vendor_map = {
        "postgresql": "postgresql", "postgres": "postgresql",
        "mysql": "mysql", "mariadb": "mysql",
        "sqlite": "sqlite", "oracle": "oracle", "mssql": "mssql",
    }
    vendor = vendor_map.get(scheme, scheme)
    dialect = resolve_dialect_by_vendor(vendor)
    async_url = dialect.normalize_url(url)

    kwargs: dict[str, Any] = {"echo": echo}
    is_memory = ":memory:" in async_url

    if is_memory:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        uses_aiomysql = "aiomysql" in async_url
        kwargs["pool_pre_ping"] = not uses_aiomysql
        kwargs["pool_use_lifo"] = True
        kwargs["pool_size"] = validate_pool_config(
            get_database_option(settings, "POOL_SIZE", 5),
            "POOL_SIZE", min_val=1, max_val=100, default=5,
        )
        kwargs["max_overflow"] = validate_pool_config(
            get_database_option(settings, "MAX_OVERFLOW", 10),
            "MAX_OVERFLOW", min_val=0, max_val=200, default=10,
        )
        kwargs["pool_recycle"] = validate_pool_config(
            get_database_option(settings, "POOL_RECYCLE", 3600),
            "POOL_RECYCLE", min_val=60, max_val=86400, default=3600,
        )
        kwargs["pool_timeout"] = validate_pool_config(
            get_database_option(settings, "POOL_TIMEOUT", 30),
            "POOL_TIMEOUT", min_val=1, max_val=300, default=30,
        )

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
            execution_options={"compiled_cache": _compiled_cache},
            **kwargs,
        )
    except (ModuleNotFoundError, ImportError) as exc:
        if "asyncpg" in async_url or "aiomysql" in async_url:
            return cast("AsyncEngine", MissingDriverAsyncEngine(async_url, echo, exc.name or ""))
        raise
    except Exception as exc:
        if "Could not parse" in str(exc) or "ArgumentError" in type(exc).__name__:
            raise ValueError(
                f"Database URL is not a valid SQLAlchemy connection string: {url!r}\n"
                f"Expected format: driver+async_driver://user:password@host:port/dbname\n"
                f"Examples:\n"
                f"  PostgreSQL: postgresql+asyncpg://user:password@localhost:5432/dbname\n"
                f"  SQLite:     sqlite+aiosqlite:///db.sqlite3\n"
                f"  MySQL:      mysql+aiomysql://user:password@localhost:3306/dbname"
            ) from exc
        raise

    dialect.configure_engine(engine, async_url)

    return engine


async def get_connection() -> AsyncConnection:
    """Return an async database connection.

    If a per-request connection is active (via :func:`request_connection`), it
    is returned directly so that multiple ORM calls within a single request
    share the same underlying database connection.  Otherwise a fresh
    connection is acquired from the pool.
    """
    req_conn = _request_conn.get()
    if req_conn is not None:
        return req_conn
    engine = await get_engine()
    return engine.connect()


@asynccontextmanager
async def request_connection() -> AsyncGenerator[AsyncConnection]:
    """Pin a single pooled connection for the duration of a request.

    All ``get_connection()`` calls made inside this context manager will
    return the *same* connection, eliminating per-query pool round-trips.

    Usage (typically inside middleware)::

        async with request_connection() as conn:
            # Every ORM call in this block reuses *conn*.
            posts = await Post.objects.filter(published=True).all()
            count = await Post.objects.count()
    """
    engine = await get_engine()
    async with engine.connect() as conn:
        token = _request_conn.set(conn)
        try:
            yield conn
        finally:
            _request_conn.reset(token)


async def init_db(drop_first: bool = False) -> None:
    """Create all registered tables.  Optionally drop them first.

    Args:
        drop_first: If True, drop all tables before creating them.
    """
    engine = await get_engine()

    if drop_first:
        # Disable FK checks before dropping cross-referenced tables.
        if "sqlite" in str(engine.url):
            async with engine.begin() as conn:
                await conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
                await conn.run_sync(metadata.drop_all)
                await conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        else:
            async with engine.begin() as conn:
                await conn.run_sync(metadata.drop_all)

        rebuild_all_tables()

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def close_db() -> None:
    """Dispose all engines, pooled connections, and clean up stale locks."""
    global _engine
    lock = get_engine_lock()
    async with lock:
        await dispose_per_loop_engines(_engines_per_loop)
        if _engine is not None:
            await _engine.dispose()
            _engine = None
    # Clear stale per-loop engines from all registered backends so that
    # subsequent configure_db() calls are not bypassed by cached entries.
    for backend in connections.backends.values():
        await dispose_per_loop_engines(backend.engines_per_loop)
        backend.engine = None
    cleanup_stale_locks()


def reset_engine() -> None:
    """Drop all engine references without disposing pooled connections."""
    global _engine
    _engine = None
    _engines_per_loop.clear()
    for backend in connections.backends.values():
        backend.engine = None
        backend.engines_per_loop.clear()
    cleanup_stale_locks()


async def configure_db(database_url: str, echo: bool = False) -> None:
    """Explicitly configure the database engine (call before init_db).

    Disposes any existing engine before replacing it so that pooled
    connections are not leaked.
    """
    global _engine
    lock = get_engine_lock()
    async with lock:
        await dispose_per_loop_engines(_engines_per_loop)
        if _engine is not None:
            await _engine.dispose()
        _engine = create_engine(database_url, echo)

        loop = get_running_loop_or_none()
        if loop is not None:
            _engines_per_loop[id(loop)] = _engine

    existing = connections.backends.get("default")
    existing_config = None
    if existing is not None:
        existing_config = existing.config

    if existing_config is not None:
        existing_config["OPTIONS"]["URL"] = database_url
        existing_config["OPTIONS"]["ECHO"] = echo
        connections.setup_alias("default", existing_config)
    else:
        db_config = getattr(settings, "DATABASES", {})
        default_config = db_config.get("default", {}) if isinstance(db_config, dict) else {}
        backend_path = default_config.get(
            "BACKEND", "openviper.db.backends.DefaultDatabaseBackend"
        )
        config: dict[str, object] = {
            "BACKEND": backend_path,
            "OPTIONS": {
                "URL": database_url,
                "ECHO": echo,
            },
            "ROLE": "primary",
        }
        connections.setup_alias("default", config)
    connections.initialized = True

    backend = connections.backends.get("default")
    if backend is not None and _engine is not None:
        backend.engine = _engine
        loop = get_running_loop_or_none()
        if loop is not None:
            backend.engines_per_loop[id(loop)] = _engine


@asynccontextmanager
async def atomic() -> AsyncGenerator[AsyncConnection]:
    """Async context manager that wraps a block of ORM operations in a transaction.

    On normal exit the transaction is committed.  On any exception it is
    rolled back and the exception is re-raised.

    Usage::

        from openviper.db.connection import atomic

        async with atomic():
            await Post.objects.create(title="Hello")
            await Tag.objects.create(name="python")
            # Both rows committed together, or both rolled back on error.

    .. note::

        OpenViper uses SQLAlchemy's async engine with connection-per-operation
        semantics.  ``atomic()`` opens a dedicated connection and begins an
        explicit transaction.  ORM calls made *inside* the block that do not
        reuse this connection will start their own auto-commit transactions.
        For full transactional integrity across multiple statements, pass the
        connection obtained here to the lower-level executor helpers.
    """
    engine = await get_engine()
    async with engine.begin() as conn:
        conn_token = _request_conn.set(conn)
        alias_token = _transaction_alias.set("default")
        try:
            yield conn
        finally:
            _transaction_alias.reset(alias_token)
            _request_conn.reset(conn_token)


@asynccontextmanager
async def transaction(
    using: str | None = None,
    read_only: bool = False,
) -> AsyncGenerator[AsyncConnection]:
    """Async context manager for a transaction pinned to a database alias.

    When *using* is provided, the transaction runs on the backend for
    that alias and pins the routing context so that all ORM calls
    inside the block use the same database.

    When *using* is ``None``, the current context alias or the
    default alias is used.

    If *read_only* is ``True`` and the alias is configured as
    read-only, the transaction is allowed.  Write operations
    inside a read-only transaction on a read-only alias raise
    ``DatabaseReadOnlyError``.

    Usage::

        from openviper.db.connection import transaction

        async with transaction(using='default'):
            await Post.objects.create(title="Hello")
            await Tag.objects.create(name="python")
    """
    alias = using or current_db_alias.get()
    backend = connections.get(alias)

    if not read_only and backend.is_read_only:
        raise DatabaseReadOnlyError(
            f"Cannot open a write transaction on read-only alias '{alias}'."
        )

    token = set_current_alias(alias)
    try:
        engine = await backend.create_engine()
        async with engine.begin() as conn:
            conn_token = _request_conn.set(conn)
            alias_token = _transaction_alias.set(alias)
            write_token = _transaction_writes_allowed.set(not backend.is_read_only)
            try:
                yield conn
            finally:
                _transaction_writes_allowed.reset(write_token)
                _transaction_alias.reset(alias_token)
                _request_conn.reset(conn_token)
    finally:
        reset_current_alias(token)
