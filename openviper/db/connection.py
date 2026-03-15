"""Database connection management using SQLAlchemy async engine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from openviper.conf import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_metadata: sa.MetaData = sa.MetaData()
_engine_lock: asyncio.Lock | None = None

# Per-request connection for reuse across multiple ORM calls.
_request_conn: ContextVar[AsyncConnection | None] = ContextVar("_request_conn", default=None)

# Shared compiled-statement cache (thread-safe dict used by SQLAlchemy).
_compiled_cache: dict[Any, Any] = {}


def _get_engine_lock() -> asyncio.Lock:
    """Return the module-level engine lock, creating it lazily (event-loop-aware)."""
    global _engine_lock
    if _engine_lock is None:
        _engine_lock = asyncio.Lock()
    return _engine_lock


def get_metadata() -> sa.MetaData:
    return _metadata


def _validate_pool_config(value: Any, name: str, min_val: int, max_val: int, default: int) -> int:
    """Validate and bound pool configuration values.

    Prevents resource exhaustion from extremely large pool settings.

    Args:
        value: The configuration value to validate
        name: Setting name (for logging)
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        default: Default value if validation fails

    Returns:
        Validated integer value within bounds
    """
    try:
        int_val = int(value)
        if not (min_val <= int_val <= max_val):  # pylint: disable=superfluous-parens
            logger.warning(
                f"{name}={int_val} outside safe range [{min_val}, {max_val}], "
                f"clamping to valid range"
            )
            return min(max_val, max(min_val, int_val))
        return int_val
    except (ValueError, TypeError) as e:
        logger.warning(f"{name} invalid value {value!r}: {e}, using default {default}")
        return default


async def get_engine() -> AsyncEngine:
    """Return (or lazily create) the shared async engine.

    Uses double-checked locking: the fast path reads ``_engine`` without
    acquiring the lock.  The lock is acquired only when ``_engine`` is ``None``,
    preventing two coroutines from both entering ``_create_engine``.
    """
    global _engine

    # Fast path — no lock required once the engine is initialised.
    if _engine is not None:
        return _engine

    lock = _get_engine_lock()
    async with lock:
        # Re-check: another coroutine may have initialised while we waited.
        if _engine is not None:
            return _engine

        _engine = _create_engine(settings.DATABASE_URL, settings.DATABASE_ECHO)

    return _engine


def _create_engine(url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL."""
    replacements = {
        "sqlite:///": "sqlite+aiosqlite:///",
        "sqlite://": "sqlite+aiosqlite://",
        "postgresql://": "postgresql+asyncpg://",
        "postgres://": "postgresql+asyncpg://",
        "mysql://": "mysql+aiomysql://",
        "mariadb://": "mysql+aiomysql://",
        "oracle://": "oracle+oracledb_async://",
        "mssql://": "mssql+aioodbc://",
    }
    async_url = url
    for old, new in replacements.items():
        if url.startswith(old):
            async_url = new + url[len(old) :]
            break

    kwargs: dict[str, Any] = {"echo": echo}
    is_memory = ":memory:" in async_url

    if is_memory:
        # In-memory SQLite: static pool so the same connection is reused across
        # coroutines (no cross-thread sharing needed for aiosqlite).
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        # Pool configuration from settings (with safe defaults and bounds checking).
        # Async engines hold connections only during active awaits, so a smaller
        # pool_size with higher max_overflow handles burst traffic more efficiently
        # than a large pre-allocated pool.
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = _validate_pool_config(
            getattr(settings, "DATABASE_POOL_SIZE", 10),
            "DATABASE_POOL_SIZE",
            min_val=1,
            max_val=100,
            default=10,
        )
        kwargs["max_overflow"] = _validate_pool_config(
            getattr(settings, "DATABASE_MAX_OVERFLOW", 90),
            "DATABASE_MAX_OVERFLOW",
            min_val=0,
            max_val=200,
            default=90,
        )
        kwargs["pool_recycle"] = _validate_pool_config(
            getattr(settings, "DATABASE_POOL_RECYCLE", 1800),
            "DATABASE_POOL_RECYCLE",
            min_val=60,
            max_val=86400,  # 24 hours max
            default=1800,
        )
        kwargs["pool_timeout"] = _validate_pool_config(
            getattr(settings, "DATABASE_POOL_TIMEOUT", 30),
            "DATABASE_POOL_TIMEOUT",
            min_val=1,
            max_val=300,
            default=30,
        )

    engine = create_async_engine(
        async_url,
        execution_options={"compiled_cache": _compiled_cache},
        **kwargs,
    )

    # Enable foreign-key enforcement for SQLite (off by default in SQLite).
    if "sqlite" in async_url:

        @sa.event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
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
                await conn.run_sync(_metadata.drop_all)
                await conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        else:
            async with engine.begin() as conn:
                await conn.run_sync(_metadata.drop_all)

    async with engine.begin() as conn:
        await conn.run_sync(_metadata.create_all)


async def close_db() -> None:
    """Dispose the engine and all pooled connections."""
    global _engine
    lock = _get_engine_lock()
    async with lock:
        if _engine is not None:
            await _engine.dispose()
            _engine = None


async def configure_db(database_url: str, echo: bool = False) -> None:
    """Explicitly configure the database engine (call before init_db).

    Disposes any existing engine before replacing it so that pooled
    connections are not leaked.
    """
    global _engine
    lock = _get_engine_lock()
    async with lock:
        if _engine is not None:
            await _engine.dispose()
        _engine = _create_engine(database_url, echo)


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
        yield conn
