"""Shared test fixtures for todoapp."""

from __future__ import annotations

import asyncio
import os
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

TODOAPP_DIR = Path(__file__).parent.parent

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENVIPER_SETTINGS_MODULE"] = "settings"
os.environ["TEMPLATES_DIR"] = str(TODOAPP_DIR / "templates")

sys.path.insert(0, str(TODOAPP_DIR))

# Import app after env is configured.
import_module("models")  # noqa: E402
from app import app  # noqa: E402

from openviper.auth import get_user_model  # noqa: E402
from openviper.db.connection import get_engine, get_metadata, init_db  # noqa: E402
from openviper.db.migrations.executor import (  # noqa: E402
    get_migration_table,
    get_soft_removed_table,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncGenerator[None]:
    """Create all tables once per test session."""
    # Ensure internal migration/soft-delete tables are in the metadata
    get_migration_table()
    get_soft_removed_table()

    await init_db(drop_first=True)
    return


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncGenerator[None]:
    """Wipe every table before each test for isolation."""
    engine = await get_engine()
    async with engine.begin() as conn:
        for table in reversed(get_metadata().sorted_tables):
            await conn.execute(table.delete())
    return


@pytest.fixture
async def user():
    """A regular (non-staff) user in the database."""
    user_model = get_user_model()
    user = user_model(username="testuser", email="test@example.com")
    await user.set_password("pass1234")
    await user.save()
    return user


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
