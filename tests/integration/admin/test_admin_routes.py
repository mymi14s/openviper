import pytest
import pytest_asyncio

from openviper.admin.registry import admin as admin_registry
from openviper.admin.site import get_admin_site
from openviper.db.connection import init_db
from tests.factories.admin_factory import create_admin_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_admin_db():
    from openviper.db.connection import close_db

    await init_db(drop_first=True)
    admin_registry.clear()
    yield
    await close_db()
    admin_registry.clear()


@pytest_asyncio.fixture
async def admin_app(app_fixture):
    from openviper.admin.middleware import AdminMiddleware
    from openviper.middleware.auth import AuthenticationMiddleware

    # Add necessary middleware for admin tests
    app_fixture._extra_middleware.extend([AuthenticationMiddleware, AdminMiddleware])
    app_fixture._middleware_app = None  # Force rebuild
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def admin_client(admin_app):
    return AdminClient(admin_app)


@pytest.mark.asyncio
async def test_admin_dashboard_access(admin_client):
    admin_user = await create_admin_user()
    admin_client.login(admin_user)

    response = await admin_client.get("/admin/api/dashboard/")
    assert response.status_code == 200
    data = response.json()
    assert "stats" in data
    assert "recent_activity" in data


@pytest.mark.asyncio
async def test_admin_config_endpoint(admin_client):
    admin_user = await create_admin_user()
    admin_client.login(admin_user)

    response = await admin_client.get("/admin/api/config/")
    assert response.status_code == 200
    data = response.json()
    assert "admin_title" in data
    assert "admin_header_title" in data
    assert "admin_footer_title" in data
    assert data["admin_title"] == "OpenViper Admin"  # default value
    assert data["admin_header_title"] == "OpenViper"  # default value
    assert data["admin_footer_title"] == "OpenViper Admin"  # default value


@pytest.mark.asyncio
async def test_admin_models_list_access(admin_client):
    admin_user = await create_admin_user()
    admin_client.login(admin_user)

    response = await admin_client.get("/admin/api/models/")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert "apps" in data


@pytest.mark.asyncio
async def test_admin_crud_workflow(admin_client):

    admin_user = await create_admin_user()
    admin_client.login(admin_user)

    # Create
    response = await admin_client.post(
        "/admin/api/models/auth/role/", data={"name": "Test Role", "description": "Test"}
    )
    assert response.status_code == 201
    role_id = response.json()["id"]

    # List
    response = await admin_client.get("/admin/api/models/auth/role/list/")
    assert response.status_code == 200
    assert any(item["name"] == "Test Role" for item in response.json()["items"])

    # Get Detail
    response = await admin_client.get(f"/admin/api/models/auth/role/{role_id}/")
    assert response.status_code == 200
    assert response.json()["instance"]["name"] == "Test Role"

    # Update
    response = await admin_client.put(
        f"/admin/api/models/auth/role/{role_id}/", data={"name": "Updated Role"}
    )
    assert response.status_code == 200

    # Delete
    response = await admin_client.delete(f"/admin/api/models/auth/role/{role_id}/")
    assert response.status_code == 200
