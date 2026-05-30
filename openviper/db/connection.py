"""Database connection management using SQLAlchemy async engine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from openviper.conf import settings
from openviper.db.backends.operations import DatabaseOperations
from openviper.db.backends.sqlalchemy import MissingDriverAsyncEngine
from openviper.db.connections import connections
from openviper.db.exceptions import DatabaseReadOnlyError
from openviper.db.routing.context import current_db_alias, reset_current_alias, set_current_alias
from openviper.db.shared_metadata import metadata
from openviper.db.utils import BoundedDict, _cleanup_stale_locks, get_per_loop_lock

logger = logging.getLogger(__name__)


_engine: AsyncEngine | None = None

# Per-request connection for reuse across multiple ORM calls.
_request_conn: ContextVar[AsyncConnection | None] = ContextVar("_request_conn", default=None)
_transaction_alias: ContextVar[str | None] = ContextVar("_transaction_alias", default=None)
_transaction_writes_allowed: ContextVar[bool] = ContextVar(
    "_transaction_writes_allowed",
    default=True,
)

# Shared compiled-statement cache with bounded size.  SQLAlchemy accesses
# this dict from multiple threads during statement compilation.  CPython's
# GIL guarantees that individual dict operations (getitem, setitem) are
# atomic.  A maximum size prevents unbounded memory growth under workloads
# with many unique query patterns.
_COMPILED_CACHE_MAX_SIZE: int = 2048
_compiled_cache: BoundedDict = BoundedDict(_COMPILED_CACHE_MAX_SIZE)

# Per-event-loop engine lock storage to avoid cross-loop errors.
# Cleaned up when the engine is disposed to prevent memory leaks from
# stale event loops in long-running processes (test runners, workers).
_engine_lock_per_loop: dict[int, asyncio.Lock] = {}


def cleanup_stale_locks() -> None:
    """Remove lock entries for event loops that are no longer running.

    Called during engine disposal to prevent unbounded growth of the
    per-loop lock dict in processes that create and destroy event loops.
    """
    _cleanup_stale_locks(_engine_lock_per_loop)


def get_engine_lock() -> asyncio.Lock:
    """Return a per-event-loop engine lock, creating lazily."""
    return get_per_loop_lock(_engine_lock_per_loop)


def get_metadata() -> sa.MetaData:
    return metadata


def validate_pool_config(value: object, name: str, min_val: int, max_val: int, default: int) -> int:
    """Validate and bound pool configuration values.

    Prevents resource exhaustion from extremely large pool settings.
    Raises on non-numeric values to catch misconfiguration early.

    Args:
        value: The configuration value to validate
        name: Setting name (for logging)
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        default: Default value if validation fails

    Returns:
        Validated integer value within bounds

    Raises:
        ValueError: If value is not convertible to an integer.
    """
    if value is None:
        return default
    if not isinstance(value, (int, float, str, bytes)):
        value = str(value)
    try:
        int_val = int(value)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Database pool setting {name} has invalid value {value!r}: {e}. "
            f"Expected an integer between {min_val} and {max_val}."
        ) from e
    if not (min_val <= int_val <= max_val):
        logger.warning(
            f"{name}={int_val} outside safe range [{min_val}, {max_val}], clamping to valid range"
        )
        return min(max_val, max(min_val, int_val))
    return int_val


async def get_engine() -> AsyncEngine:
    """Return (or lazily create) the shared async engine.

    Uses double-checked locking: the fast path reads ``_engine`` without
    acquiring the lock.  The lock is acquired only when ``_engine`` is ``None``,
    preventing two coroutines from both entering ``create_engine``.
    """
    global _engine

    # Fast path - no lock required once the engine is initialised.
    if _engine is not None:
        return _engine

    lock = get_engine_lock()
    async with lock:
        # Re-check: another coroutine may have initialised while we waited.
        if _engine is not None:
            return _engine

        _engine = create_engine(
            cast("str", settings.DATABASE_URL),
            cast("bool", settings.DATABASE_ECHO),
        )

    return _engine


_operations = DatabaseOperations()


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL."""
    async_url = _operations.normalize_url(url)

    kwargs: dict[str, Any] = {"echo": echo}
    is_memory = ":memory:" in async_url

    if is_memory:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_use_lifo"] = True
        kwargs["pool_size"] = validate_pool_config(
            getattr(settings, "DATABASE_POOL_SIZE", 20),
            "DATABASE_POOL_SIZE",
            min_val=1,
            max_val=100,
            default=20,
        )
        kwargs["max_overflow"] = validate_pool_config(
            getattr(settings, "DATABASE_MAX_OVERFLOW", 80),
            "DATABASE_MAX_OVERFLOW",
            min_val=0,
            max_val=200,
            default=80,
        )
        kwargs["pool_recycle"] = validate_pool_config(
            getattr(settings, "DATABASE_POOL_RECYCLE", 900),
            "DATABASE_POOL_RECYCLE",
            min_val=60,
            max_val=86400,  # 24 hours max
            default=900,
        )
        kwargs["pool_timeout"] = validate_pool_config(
            getattr(settings, "DATABASE_POOL_TIMEOUT", 10),
            "DATABASE_POOL_TIMEOUT",
            min_val=1,
            max_val=300,
            default=10,
        )

        if "asyncpg" in async_url:
            kwargs.setdefault("connect_args", {})
            kwargs["connect_args"]["prepared_statement_cache_size"] = validate_pool_config(
                getattr(settings, "DATABASE_PREPARED_STMT_CACHE", 256),
                "DATABASE_PREPARED_STMT_CACHE",
                min_val=0,
                max_val=2048,
                default=256,
            )

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

    if "sqlite" in async_url:

        @sa.event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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
        # SQLite cannot drop tables with active FK constraints in the wrong order.
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


async def close_db() -> None:
    """Dispose the engine, all pooled connections, and clean up stale locks."""
    global _engine
    lock = get_engine_lock()
    async with lock:
        if _engine is not None:
            await _engine.dispose()
            _engine = None
    cleanup_stale_locks()


async def configure_db(database_url: str, echo: bool = False) -> None:
    """Explicitly configure the database engine (call before init_db).

    Disposes any existing engine before replacing it so that pooled
    connections are not leaked.
    """
    global _engine
    lock = get_engine_lock()
    async with lock:
        if _engine is not None:
            await _engine.dispose()
        _engine = create_engine(database_url, echo)


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
