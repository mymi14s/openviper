"""Tests for session-scoped database setup and SessionDatabase descriptor."""

from __future__ import annotations

import pytest

from openviper.testing.database import (
    SessionDatabase,
    assert_safe_database_url,
    build_session_database,
    derive_test_database_url,
    resolve_test_database_url,
)
from openviper.testing.settings import (
    DatabaseIsolation,
    OpenViperTestingConfigError,
    override_openviper_settings,
)

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


# ── derive_test_database_url ──────────────────────────────────────────────


def test_derive_prefixes_networked_database_name() -> None:
    derived = derive_test_database_url("postgresql+asyncpg://user:secret@host:5432/app")

    assert derived == "postgresql+asyncpg://user:secret@host:5432/test_app"


def test_derive_preserves_password() -> None:
    derived = derive_test_database_url("postgresql+asyncpg://user:secret@host/app")

    assert "secret" in derived
    assert "***" not in derived


def test_derive_prefixes_sqlite_file_basename_only() -> None:
    derived = derive_test_database_url("sqlite+aiosqlite:////var/db/app.sqlite3")

    assert derived == "sqlite+aiosqlite:////var/db/test_app.sqlite3"


def test_derive_leaves_memory_url_unchanged() -> None:
    url = "sqlite+aiosqlite:///:memory:"

    assert derive_test_database_url(url) == url


def test_derive_is_idempotent_for_already_prefixed_name() -> None:
    url = "postgresql+asyncpg://u:p@h/test_app"

    assert derive_test_database_url(url) == url


# ── resolve_test_database_url ─────────────────────────────────────────────


def test_resolve_in_memory_isolation_always_uses_memory() -> None:
    url = resolve_test_database_url("postgresql+asyncpg://host/app", "in_memory")

    assert url == "sqlite+aiosqlite:///:memory:"


def test_resolve_uses_explicit_url_verbatim() -> None:
    explicit = "postgresql+asyncpg://host/test_explicit"
    url = resolve_test_database_url(explicit, "transaction")

    assert url == explicit


def test_resolve_derives_dedicated_test_db_from_settings() -> None:
    databases = {
        "default": {"OPTIONS": {"URL": "postgresql+asyncpg://user:pw@host:5432/shop"}},
    }
    with override_openviper_settings(DATABASES=databases):
        url = resolve_test_database_url(None, "transaction")

    assert url == "postgresql+asyncpg://user:pw@host:5432/test_shop"


def test_resolve_falls_back_to_memory_without_configured_db() -> None:
    databases = {"default": {"OPTIONS": {"URL": ""}}}
    with override_openviper_settings(DATABASES=databases):
        url = resolve_test_database_url(None, "transaction")

    assert url == "sqlite+aiosqlite:///:memory:"
