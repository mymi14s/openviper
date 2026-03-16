"""Unit tests for openviper/db/connection.py."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

import openviper.db.connection as mod
from openviper.db.connection import (
    _create_engine,
    _get_engine_lock,
    _request_conn,
    _validate_pool_config,
    atomic,
    close_db,
    configure_db,
    get_connection,
    get_engine,
    get_metadata,
    init_db,
    request_connection,
)


@pytest.fixture(autouse=True)
async def reset_engine():
    """Reset module-level _engine before and after each test to prevent state leaks."""
    old = mod._engine
    mod._engine = None
    yield
    if mod._engine is not None and mod._engine is not old:
        await mod._engine.dispose()
    mod._engine = old


# ---------------------------------------------------------------------------
# get_metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_returns_metadata_instance(self):
        meta = get_metadata()
        assert isinstance(meta, sa.MetaData)

    def test_same_object_each_call(self):
        assert get_metadata() is get_metadata()


# ---------------------------------------------------------------------------
# _get_engine_lock
# ---------------------------------------------------------------------------


class TestGetEngineLock:
    def test_returns_lock(self):
        lock = _get_engine_lock()
        assert isinstance(lock, asyncio.Lock)

    def test_same_object_cached(self):
        l1 = _get_engine_lock()
        l2 = _get_engine_lock()
        assert l1 is l2


# ---------------------------------------------------------------------------
# _validate_pool_config
# ---------------------------------------------------------------------------


class TestValidatePoolConfig:
    def test_valid_value_returned(self):
        result = _validate_pool_config(20, "POOL_SIZE", 1, 100, 20)
        assert result == 20

    def test_below_min_clamped(self):
        result = _validate_pool_config(0, "POOL_SIZE", 1, 100, 20)
        assert result == 1

    def test_above_max_clamped(self):
        result = _validate_pool_config(999, "POOL_SIZE", 1, 100, 20)
        assert result == 100

    def test_string_int_converted(self):
        result = _validate_pool_config("15", "POOL_SIZE", 1, 100, 20)
        assert result == 15

    def test_invalid_string_raises_value_error(self):
        with pytest.raises(ValueError, match="invalid value"):
            _validate_pool_config("not_a_number", "POOL_SIZE", 1, 100, 20)

    def test_none_returns_default(self):
        result = _validate_pool_config(None, "POOL_SIZE", 1, 100, 20)
        assert result == 20

    def test_exact_min_boundary(self):
        result = _validate_pool_config(1, "POOL_SIZE", 1, 100, 20)
        assert result == 1

    def test_exact_max_boundary(self):
        result = _validate_pool_config(100, "POOL_SIZE", 1, 100, 20)
        assert result == 100


# ---------------------------------------------------------------------------
# _create_engine
# ---------------------------------------------------------------------------


class TestCreateEngine:
    @pytest.mark.asyncio
    async def test_sqlite_url_converted(self):
        engine = _create_engine("sqlite:///./test.db")
        assert "aiosqlite" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_sqlite_memory_url(self):
        engine = _create_engine("sqlite:///:memory:")
        assert "aiosqlite" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_sqlite_memory_uses_static_pool(self):
        engine = _create_engine("sqlite:///:memory:")
        assert isinstance(engine.pool, StaticPool)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_already_async_url_passthrough(self):
        # URL that doesn't match any prefix — kept as-is
        engine = _create_engine("sqlite+aiosqlite:///./test.db")
        assert "aiosqlite" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_echo_flag_passed(self):
        engine = _create_engine("sqlite:///:memory:", echo=True)
        assert engine.echo is True
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_postgresql_url_converted(self):
        # We don't actually connect — just verify URL rewriting
        engine = _create_engine("postgresql://user:pass@localhost/db")
        assert "asyncpg" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_postgres_short_url_converted(self):
        engine = _create_engine("postgres://user:pass@localhost/db")
        assert "asyncpg" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_mysql_url_converted(self):
        engine = _create_engine("mysql://user:pass@localhost/db")
        assert "aiomysql" in str(engine.url)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_mariadb_url_converted(self):
        engine = _create_engine("mariadb://user:pass@localhost/db")
        assert "aiomysql" in str(engine.url)
        await engine.dispose()


# ---------------------------------------------------------------------------
# get_engine (lazy init + double-checked locking)
# ---------------------------------------------------------------------------


class TestGetEngine:
    @pytest.mark.asyncio
    async def test_returns_engine(self):

        old = mod._engine
        mod._engine = None
        try:
            with patch("openviper.db.connection.settings") as mock_settings:
                mock_settings.DATABASE_URL = "sqlite:///:memory:"
                mock_settings.DATABASE_ECHO = False
                mock_settings.DATABASE_POOL_SIZE = 5
                mock_settings.DATABASE_MAX_OVERFLOW = 10
                mock_settings.DATABASE_POOL_RECYCLE = 300
                engine = await get_engine()
                assert engine is not None
        finally:
            await close_db()
            mod._engine = old

    @pytest.mark.asyncio
    async def test_caches_engine(self):

        old = mod._engine
        mod._engine = None
        try:
            with patch("openviper.db.connection.settings") as mock_settings:
                mock_settings.DATABASE_URL = "sqlite:///:memory:"
                mock_settings.DATABASE_ECHO = False
                mock_settings.DATABASE_POOL_SIZE = 5
                mock_settings.DATABASE_MAX_OVERFLOW = 10
                mock_settings.DATABASE_POOL_RECYCLE = 300
                e1 = await get_engine()
                e2 = await get_engine()
                assert e1 is e2
        finally:
            await close_db()
            mod._engine = old

    @pytest.mark.asyncio
    async def test_fast_path_returns_cached(self):
        """When _engine is already set, lock is not acquired."""

        sentinel = MagicMock()
        old = mod._engine
        mod._engine = sentinel
        try:
            result = await get_engine()
            assert result is sentinel
        finally:
            mod._engine = old


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


class TestGetConnection:
    @pytest.mark.asyncio
    async def test_returns_request_conn_when_set(self):

        sentinel = MagicMock()
        token = _request_conn.set(sentinel)
        try:
            conn = await get_connection()
            assert conn is sentinel
        finally:
            _request_conn.reset(token)

    @pytest.mark.asyncio
    async def test_returns_new_connection_when_not_set(self):

        token = _request_conn.set(None)
        try:
            mock_engine = MagicMock()
            mock_conn = MagicMock()
            mock_engine.connect.return_value = mock_conn
            with patch(
                "openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)
            ):
                conn = await get_connection()
                assert conn is mock_conn
        finally:
            _request_conn.reset(token)


# ---------------------------------------------------------------------------
# request_connection context manager
# ---------------------------------------------------------------------------


class TestRequestConnection:
    @pytest.mark.asyncio
    async def test_pins_connection(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            async with request_connection() as conn:
                assert conn is mock_conn
                # While inside, _request_conn is set
                assert _request_conn.get() is mock_conn

        # After exiting, reset
        assert _request_conn.get() is None

    @pytest.mark.asyncio
    async def test_resets_on_exception(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            with pytest.raises(ValueError, match="inner error"):
                async with request_connection():
                    raise ValueError("inner error")

        assert _request_conn.get() is None


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


class TestInitDb:
    @pytest.mark.asyncio
    async def test_init_creates_tables(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.run_sync = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_engine.url = "sqlite:///:memory:"

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            await init_db()
            mock_conn.run_sync.assert_awaited()

    @pytest.mark.asyncio
    async def test_init_drop_first_non_sqlite(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.run_sync = AsyncMock()
        begin_ctx = MagicMock()
        begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        begin_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = begin_ctx
        mock_engine.url = MagicMock()
        mock_engine.url.__str__ = MagicMock(
            return_value="postgresql+asyncpg://user:pass@localhost/db"
        )

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            await init_db(drop_first=True)
            # run_sync called twice: once for drop_all, once for create_all
            assert mock_conn.run_sync.await_count == 2


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------


class TestCloseDb:
    @pytest.mark.asyncio
    async def test_close_disposes_engine(self):

        mock_engine = AsyncMock()
        old = mod._engine
        mod._engine = mock_engine
        try:
            await close_db()
            mock_engine.dispose.assert_awaited_once()
            assert mod._engine is None
        finally:
            mod._engine = old

    @pytest.mark.asyncio
    async def test_close_when_no_engine(self):

        old = mod._engine
        mod._engine = None
        try:
            # Should not raise
            await close_db()
        finally:
            mod._engine = old


# ---------------------------------------------------------------------------
# configure_db
# ---------------------------------------------------------------------------


class TestConfigureDb:
    @pytest.mark.asyncio
    async def test_configure_replaces_engine(self):

        old = mod._engine
        mod._engine = None
        try:
            await configure_db("sqlite:///:memory:")
            assert mod._engine is not None
        finally:
            if mod._engine:
                await mod._engine.dispose()
            mod._engine = old

    @pytest.mark.asyncio
    async def test_configure_disposes_existing_engine(self):

        old_engine = AsyncMock()
        old = mod._engine
        mod._engine = old_engine
        try:
            await configure_db("sqlite:///:memory:")
            old_engine.dispose.assert_awaited_once()
        finally:
            if mod._engine and mod._engine is not old_engine:
                await mod._engine.dispose()
            mod._engine = old


# ---------------------------------------------------------------------------
# atomic context manager
# ---------------------------------------------------------------------------


class TestAtomic:
    @pytest.mark.asyncio
    async def test_atomic_yields_connection(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            async with atomic() as conn:
                assert conn is mock_conn

    @pytest.mark.asyncio
    async def test_atomic_rollback_on_exception(self):

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        begin_ctx = MagicMock()
        begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = begin_ctx

        with patch("openviper.db.connection.get_engine", new=AsyncMock(return_value=mock_engine)):
            with pytest.raises(RuntimeError):
                async with atomic():
                    raise RuntimeError("transaction error")

            # __aexit__ called with exception info
            assert begin_ctx.__aexit__.called
