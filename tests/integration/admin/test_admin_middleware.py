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
async def middleware_app(app_fixture):
    from openviper.admin.middleware import AdminMiddleware
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.extend([AuthenticationMiddleware, AdminMiddleware])
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(middleware_app):
    return AdminClient(middleware_app)


@pytest.mark.asyncio
async def test_admin_access_check_middleware(client):
    # This tests openviper.admin.middleware.check_admin_access
    # which is used in admin API views.
    user = await create_admin_user()
    client.login(user)

    response = await client.get("/admin/api/dashboard/")
    assert response.status_code == 200
    # If middleware didn't work, it would likely fail auth or return 403/401


@pytest.mark.asyncio
async def test_admin_model_permission_middleware(client):
    # This tests openviper.admin.middleware.check_model_permission

    user = await create_admin_user()
    client.login(user)

    # Staff user by default has full permissions in our implementation
    response = await client.get("/admin/api/models/auth/role/list/")
    assert response.status_code == 200
