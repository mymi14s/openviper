"""Tests for database test helpers: safety checks and isolation descriptors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.testing.database import (
    SessionDatabase,
    TestDatabase,
    assert_safe_database_url,
    build_session_database,
    build_test_database,
    database_context,
    session_database_context,
)
from openviper.testing.settings import OpenViperTestingConfigError

# ── assert_safe_database_url ──────────────────────────────────────────────


def test_safe_url_accepts_in_memory_sqlite() -> None:
    assert_safe_database_url("sqlite+aiosqlite:///:memory:")


def test_safe_url_accepts_test_named_database() -> None:
    assert_safe_database_url("postgresql+asyncpg://localhost/test_myapp")


def test_safe_url_rejects_empty_string() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="empty"):
        assert_safe_database_url("")


def test_safe_url_rejects_whitespace_only_string() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="empty"):
        assert_safe_database_url("   ")


def test_safe_url_rejects_production_database_name() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://localhost/production")


def test_safe_url_rejects_prod_database_name() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://localhost/prod")


def test_safe_url_rejects_live_database_name() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://localhost/live")


def test_safe_url_rejects_postgres_without_test_in_name() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="test"):
        assert_safe_database_url("postgresql+asyncpg://localhost/myapp")


def test_safe_url_rejects_production_hostname() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://production/testdb")


def test_safe_url_rejects_live_hostname() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://live/testdb")


# ── build_test_database ────────────────────────────────────────────────────


def test_build_test_database_defaults_to_memory_when_no_url() -> None:
    db = build_test_database(None, "transaction", migrate=False)

    assert ":memory:" in db.url


def test_build_test_database_forces_memory_for_in_memory_isolation() -> None:
    db = build_test_database("postgresql+asyncpg://localhost/testdb", "in_memory", migrate=False)

    assert ":memory:" in db.url


def test_build_test_database_preserves_url_for_transaction_isolation() -> None:
    url = "sqlite+aiosqlite:///:memory:"
    db = build_test_database(url, "transaction", migrate=True)

    assert db.url == url
    assert db.isolation == "transaction"
    assert db.migrate is True


def test_build_test_database_sets_migrate_flag() -> None:
    db = build_test_database(None, "transaction", migrate=False)

    assert db.migrate is False


def test_test_database_is_frozen_dataclass() -> None:
    db = build_test_database(None, "transaction", migrate=False)

    with pytest.raises((AttributeError, TypeError)):
        db.migrate = True


def test_test_database_class_attr_suppresses_pytest_collection() -> None:
    assert TestDatabase.__test__ is False


# ── build_session_database ────────────────────────────────────────────────


def test_build_session_database_defaults_to_memory_when_no_url() -> None:
    session_db = build_session_database(None, "transaction")

    assert ":memory:" in session_db.url


def test_build_session_database_forces_memory_for_in_memory_isolation() -> None:
    session_db = build_session_database("postgresql+asyncpg://localhost/testdb", "in_memory")

    assert ":memory:" in session_db.url


def test_build_session_database_preserves_url_for_transaction() -> None:
    url = "sqlite+aiosqlite:///:memory:"
    session_db = build_session_database(url, "transaction")

    assert session_db.url == url
    assert session_db.isolation == "transaction"


def test_session_database_is_frozen_dataclass() -> None:
    session_db = build_session_database(None, "transaction")

    with pytest.raises((AttributeError, TypeError)):
        session_db.isolation = "recreate"


def test_session_database_class_attr_suppresses_pytest_collection() -> None:
    assert SessionDatabase.__test__ is False


# ── TestDatabase.reset ────────────────────────────────────────────────────


async def test_transaction_mode_reset_is_noop() -> None:
    db = build_test_database(None, "transaction", migrate=False)

    with patch("openviper.testing.database.init_db") as mock_init:
        await db.reset()

    assert mock_init.call_count == 0


async def test_truncate_mode_reset_calls_truncate() -> None:
    db = build_test_database(None, "truncate", migrate=False)

    with patch("openviper.testing.database.truncate_database") as mock_trunc:
        await db.reset()

    assert mock_trunc.call_count == 1


async def test_recreate_mode_reset_calls_init_db() -> None:
    db = build_test_database(None, "recreate", migrate=False)

    with patch("openviper.testing.database.init_db") as mock_init:
        await db.reset()

    assert mock_init.call_count == 1


# ── SessionDatabase.reset ─────────────────────────────────────────────────


async def test_session_truncate_mode_reset_calls_truncate() -> None:
    session_db = build_session_database(None, "truncate")

    with patch("openviper.testing.database.truncate_database") as mock_trunc:
        await session_db.reset()

    assert mock_trunc.call_count == 1


async def test_session_non_truncate_mode_reset_calls_init_db() -> None:
    session_db = build_session_database(None, "transaction")

    with patch("openviper.testing.database.init_db") as mock_init:
        await session_db.reset()

    assert mock_init.call_count == 1


# ── database_context ──────────────────────────────────────────────────────


async def test_database_context_uses_request_connection_for_transaction_mode() -> None:
    db = build_test_database(None, "transaction", migrate=False)
    entered: list[bool] = []

    async def fake_setup(self: TestDatabase) -> None:
        pass

    async def fake_teardown(self: TestDatabase) -> None:
        pass

    with (
        patch.object(TestDatabase, "setup", fake_setup),
        patch.object(TestDatabase, "teardown", fake_teardown),
        patch("openviper.testing.database.request_connection") as mock_rc,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=None)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_rc.return_value = mock_cm

        async with database_context(db):
            entered.append(True)

    assert entered == [True]
    mock_rc.assert_called_once()


async def test_database_context_calls_reset_for_non_transaction_modes() -> None:
    db = build_test_database(None, "truncate", migrate=False)
    order: list[str] = []

    async def fake_setup(self: TestDatabase) -> None:
        order.append("setup")

    async def fake_reset(self: TestDatabase) -> None:
        order.append("reset")

    async def fake_teardown(self: TestDatabase) -> None:
        order.append("teardown")

    with (
        patch.object(TestDatabase, "setup", fake_setup),
        patch.object(TestDatabase, "reset", fake_reset),
        patch.object(TestDatabase, "teardown", fake_teardown),
    ):
        async with database_context(db):
            order.append("test")

    assert order == ["setup", "test", "reset", "teardown"]


# ── session_database_context ──────────────────────────────────────────────


async def test_session_database_context_calls_setup_and_teardown() -> None:
    session_db = build_session_database(None, "transaction")
    order: list[str] = []

    async def fake_setup(self: SessionDatabase) -> None:
        order.append("setup")

    async def fake_teardown(self: SessionDatabase) -> None:
        order.append("teardown")

    with (
        patch.object(SessionDatabase, "setup", fake_setup),
        patch.object(SessionDatabase, "teardown", fake_teardown),
    ):
        async with session_database_context(session_db):
            order.append("test")

    assert order == ["setup", "test", "teardown"]
