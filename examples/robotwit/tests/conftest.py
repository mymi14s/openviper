"""Shared test fixtures for robotwit."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROBOTWIT_DIR = Path(__file__).parent.parent

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENVIPER_SETTINGS_MODULE"] = "robotwit.settings"
os.environ["TEMPLATES_DIR"] = str(ROBOTWIT_DIR / "templates")
os.environ["DEBUG"] = "1"

sys.path.insert(0, str(ROBOTWIT_DIR))

# Import all models so they register in metadata
from agents.models import Agent  # noqa: E402
import agents.models  # noqa: E402, F401
import notifications.models  # noqa: E402, F401
import timeline.models  # noqa: E402, F401
import tweets.models  # noqa: E402, F401

# Clear the build_table cache so FK references to the custom user model
# (Agent/agents_agent) are resolved correctly instead of falling back to auth_users.
from openviper.db.executor import build_table  # noqa: E402

build_table.cache_clear()

# Remove all tables from metadata so they get rebuilt with correct FK targets.
from openviper.db.connection import get_metadata  # noqa: E402

_metadata = get_metadata()
for name in list(_metadata.tables.keys()):
    _metadata.remove(_metadata.tables[name])

from openviper.db import model_registry  # noqa: E402

for _key, _model_cls in list(model_registry.registry.items()):
    _tname = getattr(_model_cls, "_table_name", "")
    if _tname:
        try:
            build_table(_tname, _model_cls)
        except Exception:
            import logging
            logging.getLogger("robotwit.tests").debug(
                "Failed to build table %s", _tname, exc_info=True
            )

# Register migration/soft-delete tables so they get created too.
from openviper.db.migrations.executor import get_migration_table, get_soft_removed_table  # noqa: E402

get_migration_table()
get_soft_removed_table()


def _create_tables():
    """Create all tables using the same engine that model saves use."""
    from openviper.db.executor import resolve_engine_for_alias

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:

        async def run():
            engine = await resolve_engine_for_alias("default", write=True)
            async with engine.begin() as conn:
                await conn.run_sync(_metadata.create_all)

        loop.run_until_complete(run())
    finally:
        loop.close()


_create_tables()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def clean_tables():
    from openviper.db.executor import resolve_engine_for_alias

    engine = await resolve_engine_for_alias("default", write=True)
    async with engine.begin() as conn:
        for table in reversed(_metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
async def agent():
    """Create a human test agent."""
    a = Agent(
        username="testuser",
        email="test@example.com",
        display_name="Test User",
        is_human=True,
        is_active=True,
    )
    await a.set_password("password123")
    await a.save()
    return a
