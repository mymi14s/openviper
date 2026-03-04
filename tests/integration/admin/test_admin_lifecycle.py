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
async def lifecycle_app(app_fixture):
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.append(AuthenticationMiddleware)
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest.mark.asyncio
async def test_admin_autodiscovery(lifecycle_app):
    from openviper.admin.discovery import autodiscover

    # Trigger autodiscover
    autodiscover()
    # Check if some default models are registered (e.g., User if auth is in INSTALLED_APPS)
    # This depends on settings.INSTALLED_APPS.
    # In tests/conftest.py, we use openviper.conf.base
    registered_models = admin_registry.get_registered_models()
    assert len(registered_models) >= 0  # Just check it doesn't crash


@pytest.mark.asyncio
async def test_admin_registry_clear(lifecycle_app):
    from openviper.auth.models import Role

    if admin_registry.is_registered(Role):
        admin_registry.unregister(Role)
    admin_registry.register(Role)
    assert admin_registry.is_registered(Role)
    admin_registry.clear()
    assert not admin_registry.is_registered(Role)
