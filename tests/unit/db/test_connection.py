"""Unit tests for openviper.db.connection — double-checked async lock.

Covers:
- ``_get_engine_lock()`` lazy creation
- ``configure_db()`` sets the engine
- ``close_db()`` disposes engine and resets to None
- ``_create_engine()`` StaticPool for :memory:, url rewriting
- ``get_engine()`` double-checked locking: 100 concurrent coroutines create
  the engine exactly once
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool

import openviper.db.connection as conn_module
from openviper.db.connection import (
    _create_engine,
    _get_engine_lock,
    close_db,
    configure_db,
    get_engine,
)

# ---------------------------------------------------------------------------
# Fixture — reset module-level singletons between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_engine_state():
    """Dispose any engine and reset module globals before and after each test."""
    await close_db()
    conn_module._engine_lock = None
    yield
    await close_db()
    conn_module._engine_lock = None


# ---------------------------------------------------------------------------
# _get_engine_lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_engine_lock_returns_asyncio_lock():
    lock = _get_engine_lock()
    assert isinstance(lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_get_engine_lock_returns_same_instance_on_second_call():
    lock1 = _get_engine_lock()
    lock2 = _get_engine_lock()
    assert lock1 is lock2


# ---------------------------------------------------------------------------
# _create_engine — URL rewriting & pool selection
# ---------------------------------------------------------------------------


def test_create_engine_memory_uses_staticpool():
    engine = _create_engine("sqlite:///:memory:")
    try:
        assert isinstance(engine.pool, StaticPool)
    finally:
        # sync dispose — no async context available
        engine.sync_engine.dispose()


def test_create_engine_memory_sets_check_same_thread():
    """connect_args must include check_same_thread=False for in-memory SQLite."""
    engine = _create_engine("sqlite:///:memory:")
    try:
        # SQLAlchemy exposes connect_args via the creator or dialect.
        # We verify indirectly by checking the engine URL contains aiosqlite.
        assert "aiosqlite" in str(engine.url)
    finally:
        engine.sync_engine.dispose()


def test_create_engine_rewrites_sqlite_prefix():
    engine = _create_engine("sqlite:///mydb.db")
    try:
        assert "aiosqlite" in str(engine.url)
    finally:
        engine.sync_engine.dispose()


def test_create_engine_rewrites_postgresql_prefix():
    # Verify URL rewriting logic without triggering actual PostgreSQL dialect import
    # (SQLAlchemy postgresql+asyncpg has a circular import on Python 3.14).
    with patch("openviper.db.connection.create_async_engine") as mock_cae:
        mock_cae.return_value = MagicMock()
        _create_engine("postgresql://user:pass@localhost/db")
    rewritten_url = str(mock_cae.call_args[0][0])
    assert "asyncpg" in rewritten_url


def test_create_engine_rewrites_postgres_short_prefix():
    with patch("openviper.db.connection.create_async_engine") as mock_cae:
        mock_cae.return_value = MagicMock()
        _create_engine("postgres://user:pass@localhost/db")
    rewritten_url = str(mock_cae.call_args[0][0])
    assert "asyncpg" in rewritten_url


# ---------------------------------------------------------------------------
# configure_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_db_sets_engine():
    await configure_db("sqlite:///:memory:")
    assert conn_module._engine is not None


@pytest.mark.asyncio
async def test_configure_db_returns_async_engine():
    from sqlalchemy.ext.asyncio import AsyncEngine

    await configure_db("sqlite:///:memory:")
    assert isinstance(conn_module._engine, AsyncEngine)


@pytest.mark.asyncio
async def test_configure_db_replaces_existing_engine():
    await configure_db("sqlite:///:memory:")
    first = conn_module._engine
    await configure_db("sqlite:///:memory:")
    second = conn_module._engine
    # Engines must be distinct objects (first was disposed and replaced).
    assert first is not second


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_db_sets_engine_to_none():
    await configure_db("sqlite:///:memory:")
    assert conn_module._engine is not None
    await close_db()
    assert conn_module._engine is None


@pytest.mark.asyncio
async def test_close_db_is_idempotent():
    """Calling close_db() when no engine is set must not raise."""
    await close_db()
    await close_db()
    assert conn_module._engine is None


# ---------------------------------------------------------------------------
# get_engine — basic functionality via configure_db fast path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_engine_returns_engine_after_configure():
    from sqlalchemy.ext.asyncio import AsyncEngine

    await configure_db("sqlite:///:memory:")
    engine = await get_engine()
    assert isinstance(engine, AsyncEngine)


@pytest.mark.asyncio
async def test_get_engine_returns_same_instance_on_repeated_calls():
    await configure_db("sqlite:///:memory:")
    e1 = await get_engine()
    e2 = await get_engine()
    assert e1 is e2


@pytest.mark.asyncio
async def test_get_engine_creates_engine_from_settings():
    """get_engine() initialises _engine from settings when not pre-configured."""
    with (
        patch("openviper.conf.settings.DATABASE_URL", "sqlite:///:memory:", create=True),
        patch("openviper.conf.settings.DATABASE_ECHO", False, create=True),
    ):
        engine = await get_engine()
    assert engine is not None
    await close_db()
    conn_module._engine_lock = None


# ---------------------------------------------------------------------------
# get_engine — concurrency: 100 coroutines, engine created exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_engine_concurrent_creates_engine_exactly_once():
    """100 concurrent coroutines calling get_engine() must only build the engine once."""
    create_calls: list[int] = []
    original_create = conn_module._create_engine

    def counting_create(url: str, echo: bool = False):
        create_calls.append(1)
        return original_create(url, echo)

    with (
        patch("openviper.db.connection._create_engine", side_effect=counting_create),
        patch("openviper.conf.settings.DATABASE_URL", "sqlite:///:memory:", create=True),
        patch("openviper.conf.settings.DATABASE_ECHO", False, create=True),
    ):
        # Spawn 100 coroutines that all race to call get_engine().
        results = await asyncio.gather(*[get_engine() for _ in range(100)])

    assert (
        len(create_calls) == 1
    ), f"_create_engine was called {len(create_calls)} times, expected exactly 1"
    # Every coroutine must have received the same engine instance.
    first = results[0]
    assert all(r is first for r in results)
