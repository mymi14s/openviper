"""Shared test fixtures for todoapp."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest

# ── Bootstrap: set env vars BEFORE any openviper import ─────────────────────
TODOAPP_DIR = Path(__file__).parent.parent

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENVIPER_SETTINGS_MODULE"] = "settings"
os.environ["TEMPLATES_DIR"] = str(TODOAPP_DIR / "templates")

sys.path.insert(0, str(TODOAPP_DIR))

# Import app after env is configured (triggers openviper.setup(force=True))
from app import app  # noqa: E402

from openviper.auth import get_user_model  # noqa: E402
from openviper.db.connection import _metadata, get_engine, init_db  # noqa: E402

# ── Event loop (session-scoped for session-scoped async fixtures) ─────────────


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Database setup / teardown ────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    """Create all tables once per test session."""
    import models  # noqa: F401 — registers Todo in SQLAlchemy metadata

    # Ensure internal migration/soft-delete tables are in the metadata
    from openviper.db.migrations.executor import _get_migration_table, _get_soft_removed_table

    _get_migration_table()
    _get_soft_removed_table()

    await init_db(drop_first=True)
    return


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncGenerator[None, None]:
    """Wipe every table before each test for isolation."""
    engine = await get_engine()
    async with engine.begin() as conn:
        for table in reversed(_metadata.sorted_tables):
            await conn.execute(table.delete())
    return


# ── Shared object fixtures ────────────────────────────────────────────────────


@pytest.fixture
async def user():
    """A regular (non-staff) user in the database."""
    User = get_user_model()  # noqa: N806
    u = User(username="testuser", email="test@example.com")
    u.set_password("pass1234")
    await u.save()
    return u


@pytest.fixture
def client():
    """Unauthenticated httpx AsyncClient backed by the app."""
    return app.test_client()


@pytest.fixture
async def auth_client(user) -> AsyncGenerator:
    """Authenticated client: logs in as *user* and yields the client."""
    c = app.test_client()
    resp = await c.post(
        "/login",
        data={"username": "testuser", "password": "pass1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code} {resp.text}"
    yield c
    await c.aclose()
