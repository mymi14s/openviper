"""Tests for session-scoped database setup and SessionDatabase descriptor."""

from __future__ import annotations

import pytest

from openviper.testing.database import (
    SessionDatabase,
    assert_safe_database_url,
    build_session_database,
)
from openviper.testing.settings import DatabaseIsolation, OpenViperTestingConfigError

# ── build_session_database ────────────────────────────────────────────────


def test_build_session_database_uses_memory_url_when_none_given() -> None:
    db = build_session_database(None, "transaction")

    assert ":memory:" in db.url


def test_build_session_database_forces_memory_for_in_memory_isolation() -> None:
    db = build_session_database("postgresql+asyncpg://localhost/testdb", "in_memory")

    assert ":memory:" in db.url


def test_build_session_database_preserves_provided_url() -> None:
    url = "sqlite+aiosqlite:///:memory:"
    db = build_session_database(url, "truncate")

    assert db.url == url


def test_build_session_database_stores_isolation_mode() -> None:
    db = build_session_database(None, "truncate")

    assert db.isolation == "truncate"


@pytest.mark.parametrize("mode", ["transaction", "truncate", "recreate", "in_memory"])
def test_build_session_database_accepts_all_isolation_modes(mode: DatabaseIsolation) -> None:
    db = build_session_database(None, mode)

    assert db.isolation == mode


# ── SessionDatabase properties ────────────────────────────────────────────


def test_session_database_is_frozen_dataclass() -> None:
    db = build_session_database(None, "transaction")

    with pytest.raises((AttributeError, TypeError)):
        db.isolation = "truncate"


def test_session_database_suppresses_pytest_collection() -> None:
    assert SessionDatabase.__test__ is False


def test_session_database_has_correct_url_attribute() -> None:
    db = build_session_database("sqlite+aiosqlite:///:memory:", "transaction")

    assert db.url == "sqlite+aiosqlite:///:memory:"


# ── safety checks (shared with TestDatabase) ─────────────────────────────


def test_session_database_url_safety_rejects_empty() -> None:
    with pytest.raises(OpenViperTestingConfigError, match="empty"):
        assert_safe_database_url("")


def test_session_database_url_safety_accepts_memory() -> None:
    assert_safe_database_url("sqlite+aiosqlite:///:memory:")


def test_session_database_url_safety_rejects_production_name() -> None:
    with pytest.raises(OpenViperTestingConfigError):
        assert_safe_database_url("postgresql+asyncpg://localhost/production")
