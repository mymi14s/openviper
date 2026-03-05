import pytest
import pytest_asyncio

from openviper.admin.registry import admin as admin_registry
from openviper.admin.site import get_admin_site
from openviper.db.connection import init_db
from tests.factories.admin_factory import create_admin_user, create_regular_user, create_staff_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_admin_db():
    from openviper.db.connection import close_db
    from openviper.middleware import auth as _auth_mod

    await init_db(drop_first=True)
    _auth_mod._USER_CACHE.clear()
    admin_registry.clear()
    yield
    await close_db()
    admin_registry.clear()


@pytest_asyncio.fixture
async def perm_app(app_fixture):
    from openviper.admin.middleware import AdminMiddleware
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.extend([AuthenticationMiddleware, AdminMiddleware])
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(perm_app):
    return AdminClient(perm_app)


@pytest.mark.asyncio
async def test_admin_access_superuser(client):
    user = await create_admin_user()
    client.login(user)
    response = await client.get("/admin/api/dashboard/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_access_staff(client):
    user = await create_staff_user()
    client.login(user)
    response = await client.get("/admin/api/dashboard/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_access_denied_regular_user(client):
    user = await create_regular_user()
    client.login(user)
    response = await client.get("/admin/api/dashboard/")
    # AdminMiddleware returns 401 for insufficient privileges in current implementation
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_access_unauthorized_anonymous(client):
    response = await client.get("/admin/api/dashboard/")
    assert response.status_code == 401
