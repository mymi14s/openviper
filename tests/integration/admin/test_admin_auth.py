import pytest
import pytest_asyncio

from openviper.admin.site import get_admin_site
from tests.factories.admin_factory import create_admin_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_admin_db():
    from openviper.db.connection import close_db, init_db
    from openviper.middleware import auth as _auth_mod

    await init_db(drop_first=True)
    _auth_mod._USER_CACHE.clear()
    yield
    await close_db()


@pytest_asyncio.fixture
async def auth_app(app_fixture):
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.append(AuthenticationMiddleware)
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(auth_app):
    return AdminClient(auth_app)


@pytest.mark.asyncio
async def test_admin_login_success(client):
    await create_admin_user(username="admin_test")

    response = await client.post(
        "/admin/api/auth/login/", data={"username": "admin_test", "password": "password123"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "admin_test"


@pytest.mark.asyncio
async def test_admin_login_failure(client):
    await create_admin_user(username="admin_fail")

    response = await client.post(
        "/admin/api/auth/login/", data={"username": "admin_fail", "password": "wrongpassword"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_me_endpoint(client):
    admin_user = await create_admin_user()
    client.login(admin_user)

    response = await client.get("/admin/api/auth/me/")
    assert response.status_code == 200
    assert response.json()["username"] == admin_user.username


@pytest.mark.asyncio
async def test_admin_refresh_token(client):
    admin_user = await create_admin_user()

    # Login to get refresh token
    login_resp = await client.post(
        "/admin/api/auth/login/", data={"username": admin_user.username, "password": "password123"}
    )
    refresh_token = login_resp.json()["refresh_token"]

    # Refresh
    response = await client.post("/admin/api/auth/refresh/", data={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()
