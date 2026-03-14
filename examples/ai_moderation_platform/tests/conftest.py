import os

import pytest

from openviper.auth.jwt import create_access_token
from openviper.db.migrations.executor import _get_migration_table, _get_soft_removed_table
from users.models import User

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENVIPER_SETTINGS_MODULE"] = "ai_moderation_platform.settings"

from ai_moderation_platform.asgi import app  # noqa: E402

from openviper.db.connection import _metadata, get_engine, init_db  # noqa: E402


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Initialize database and discover models."""
    # Ensure project models are imported

    # Ensure internal system tables are registered in metadata
    _get_migration_table()
    _get_soft_removed_table()

    await init_db(drop_first=True)
    return
    # Cleanup session engine if needed


@pytest.fixture(autouse=True)
async def clean_database():
    """Clean all tables before each test."""
    engine = await get_engine()
    async with engine.begin() as conn:
        for table in reversed(_metadata.sorted_tables):
            await conn.execute(table.delete())
    return


@pytest.fixture
async def client():
    """Return a test client for the app."""
    return app.test_client()


@pytest.fixture
async def auth_client(client, active_user):
    """Return a test client with authentication headers."""
    token = create_access_token(active_user.id, {"username": active_user.username})
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
async def active_user():
    """Create an active user for testing."""
    user = User(username="testuser", email="test@example.com", is_active=True)
    await user.set_password("password123")
    await user.save()
    return user


@pytest.fixture
async def moderator_user():
    """Create a staff/moderator user for testing."""
    user = User(username="moderator", email="mod@example.com", is_active=True, is_staff=True)
    await user.set_password("password123")
    await user.save()
    return user
