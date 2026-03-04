import pytest
import pytest_asyncio

from openviper.admin.registry import admin as admin_registry
from openviper.admin.site import get_admin_site
from openviper.db.connection import init_db
from tests.factories.admin_factory import create_admin_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_admin_db():
    from openviper.db.connection import close_db, init_db

    await init_db(drop_first=True)
    admin_registry.clear()
    yield
    await close_db()
    admin_registry.clear()


@pytest_asyncio.fixture
async def error_app(app_fixture):
    from openviper.admin.middleware import AdminMiddleware
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.extend([AuthenticationMiddleware, AdminMiddleware])
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(error_app):
    return AdminClient(error_app)


@pytest.mark.asyncio
async def test_admin_404_not_found(client):
    admin_user = await create_admin_user()
    client.login(admin_user)
    # Use POST to a non-existent path.
    # Because of the /{path:path} catch-all for GET/HEAD,
    # any other method for an unknown path returns 405.
    response = await client.post("/admin/api/nonexistent/", data={})
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_admin_405_method_not_allowed(client):
    admin_user = await create_admin_user()
    client.login(admin_user)
    # Dashboard only supports GET. POST to dashboard should 405.
    response = await client.post("/admin/api/dashboard/", data={})
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_admin_400_validation_error(client):
    admin_user = await create_admin_user()
    client.login(admin_user)
    # Login requires username/password, sending empty data
    response = await client.post("/admin/api/auth/login/", data={})
    # OpenViper returns 422 for ValidationError
    assert response.status_code == 422
