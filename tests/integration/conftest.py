"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from openviper.app import OpenViper
from openviper.auth.models import Permission, Role, User
from openviper.cache import get_cache
from openviper.conf import settings
from openviper.db.connection import get_metadata
from openviper.db.events import _background_tasks
from openviper.http.response import JSONResponse
from tests.factories.db import create_test_engine


async def _drain_tasks() -> None:
    """Wait for all model-event background tasks to complete.

    Uses asyncio.gather so multi-step coroutines (which need many event-loop
    ticks) are fully awaited rather than just yielded through once.
    """
    for _ in range(10):
        tasks = list(_background_tasks)
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture(autouse=True)
async def drain_background_tasks():
    """Drain pending model-event background tasks so they don't race with DB teardown."""
    yield
    await _drain_tasks()


@pytest.fixture
async def drain_tasks():
    """Return the drain helper so individual tests can call it between saves."""
    return _drain_tasks


@pytest.fixture(autouse=True)
def configure_test_settings():
    """Configure settings for integration tests."""
    with patch.object(type(settings), "ALLOWED_HOSTS", new=("*",), create=True):
        with patch.object(type(settings), "DEBUG", new=True, create=True):
            yield


@pytest.fixture
async def test_database():
    """Create and configure a test database with migrations."""
    engine = await create_test_engine()
    metadata = get_metadata()

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)


@pytest.fixture
async def test_cache():
    """Initialize and clear cache for tests."""
    cache = get_cache()
    await cache.clear()
    yield cache
    await cache.clear()


@pytest.fixture
async def admin_user(test_database) -> User:
    """Create an admin user with superuser privileges."""
    user = User(
        username="admin",
        email="admin@example.com",
        is_active=True,
        is_superuser=True,
        is_staff=True,
    )
    await user.set_password("admin123")
    await user.save()
    return user


@pytest.fixture
async def regular_user(test_database) -> User:
    """Create a regular user without special privileges."""
    user = User(
        username="testuser",
        email="testuser@example.com",
        is_active=True,
        is_superuser=False,
        is_staff=False,
    )
    await user.set_password("password123")
    await user.save()
    return user


@pytest.fixture
async def user_with_role(test_database, test_cache) -> tuple[User, Role]:
    """Create a user with an assigned role and permissions."""
    permission = Permission(
        codename="view_dashboard",
        name="Can view dashboard",
    )
    await permission.save()

    role = Role(
        name="viewer",
        description="Dashboard viewer role",
    )
    await role.save()

    await role.permissions.add(permission)

    user = User(
        username="roleuser",
        email="roleuser@example.com",
        is_active=True,
        is_superuser=False,
        is_staff=False,
    )
    await user.set_password("password123")
    await user.save()

    await user.roles.add(role)

    return user, role


@pytest.fixture
def test_app() -> OpenViper:
    """Create a test OpenViper application instance."""
    app = OpenViper(
        title="Test App",
        version="1.0.0",
        description="Integration test application",
    )

    @app.get("/")
    async def home():
        return {"message": "Home page"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


@pytest.fixture
def authenticated_client(test_app: OpenViper, admin_user: User) -> httpx.AsyncClient:
    """Create an authenticated test client with admin user session."""

    async def auth_middleware(scope, receive, send):
        if scope["type"] == "http":
            from openviper.core.context import current_request
            from openviper.http.request import Request

            request = Request(scope, receive, send)
            request._user = admin_user
            current_request.set(request)

        await test_app(scope, receive, send)

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_middleware),
        base_url="http://testserver",
    )


@pytest.fixture
async def sample_test_data(test_database, test_cache) -> dict[str, Any]:
    """Create sample test data for integration tests."""
    permissions = []
    for codename in ["add_user", "change_user", "delete_user", "view_user"]:
        perm = Permission(
            codename=codename,
            name=f"Can {codename.split('_')[0]} user",
        )
        await perm.save()
        permissions.append(perm)

    admin_role = Role(
        name="admin",
        description="Administrator role",
    )
    await admin_role.save()

    for perm in permissions:
        await admin_role.permissions.add(perm)

    editor_role = Role(
        name="editor",
        description="Editor role",
    )
    await editor_role.save()

    await editor_role.permissions.add(permissions[0])
    await editor_role.permissions.add(permissions[1])

    return {
        "permissions": permissions,
        "admin_role": admin_role,
        "editor_role": editor_role,
    }


@pytest.fixture
async def app_with_routes(test_database, test_cache) -> OpenViper:
    """Create an app with comprehensive routes for testing."""
    app = OpenViper(
        title="Integration Test App",
        version="1.0.0",
    )

    @app.get("/")
    async def index():
        return {"message": "Welcome"}

    @app.get("/dashboard")
    async def dashboard(request):
        if not hasattr(request, "user") or not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return {"user": request.user.username, "page": "dashboard"}

    @app.get("/users")
    async def list_users(request):
        users = await User.objects.all()
        return {"users": [{"id": u.id, "username": u.username, "email": u.email} for u in users]}

    @app.get("/users/{user_id}")
    async def get_user(user_id: int):
        user = await User.objects.filter(id=user_id).first()
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
        }

    @app.post("/users")
    async def create_user(request):
        data = await request.json()
        user = User(
            username=data["username"],
            email=data.get("email", ""),
        )
        if "password" in data:
            await user.set_password(data["password"])
        await user.save()
        return JSONResponse(
            {"id": user.id, "username": user.username},
            status_code=201,
        )

    @app.put("/users/{user_id}")
    async def update_user(user_id: int, request):
        user = await User.objects.filter(id=user_id).first()
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)

        data = await request.json()
        if "email" in data:
            user.email = data["email"]
        if "password" in data:
            await user.set_password(data["password"])
        await user.save()

        return {"id": user.id, "username": user.username, "email": user.email}

    @app.delete("/users/{user_id}")
    async def delete_user(user_id: int):
        user = await User.objects.filter(id=user_id).first()
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)
        await user.delete()
        return JSONResponse({"message": "Deleted"}, status_code=204)

    @app.get("/protected")
    async def protected_route(request):
        if not hasattr(request, "user") or not request.user or not request.user.is_authenticated:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if not request.user.is_staff:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return {"message": "Protected resource"}

    return app
