"""Database connection management using SQLAlchemy async engine."""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

_engine: AsyncEngine | None = None
_metadata: sa.MetaData = sa.MetaData()
_engine_lock: asyncio.Lock | None = None


def _get_engine_lock() -> asyncio.Lock:
    """Return the module-level engine lock, creating it lazily (event-loop-aware)."""
    global _engine_lock
    if _engine_lock is None:
        _engine_lock = asyncio.Lock()
    return _engine_lock


def get_metadata() -> sa.MetaData:
    return _metadata


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
        from openviper.conf import settings as _settings

        _engine = _create_engine(_settings.DATABASE_URL, _settings.DATABASE_ECHO)

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
        # Pool configuration from settings (with safe defaults).
        from openviper.conf import settings as _settings

        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = int(getattr(_settings, "DATABASE_POOL_SIZE", 5))
        kwargs["max_overflow"] = int(getattr(_settings, "DATABASE_MAX_OVERFLOW", 10))
        kwargs["pool_recycle"] = int(getattr(_settings, "DATABASE_POOL_RECYCLE", 1800))

    engine = create_async_engine(async_url, **kwargs)

    # Enable foreign-key enforcement for SQLite (off by default in SQLite).
    if "sqlite" in async_url:

        @sa.event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


async def get_connection() -> AsyncConnection:
    """Return an async database connection from the pool."""
    engine = await get_engine()
    return engine.connect()


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
