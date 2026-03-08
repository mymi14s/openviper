import asyncio
import logging
import shutil
import tempfile
import typing
from collections.abc import AsyncGenerator, Generator

import pytest

import httpx
from openviper.app import OpenViper
from openviper.conf import settings
from openviper.conf.settings import Settings


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def global_settings_fixture() -> Settings:
    """Configure test-specific settings, resetting any prior lazy init first."""
    object.__setattr__(settings, "_instance", None)
    object.__setattr__(settings, "_configured", False)
    settings.configure(
        Settings(
            MIDDLEWARE=(),
            DEBUG=True,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
        )
    )
    return typing.cast(Settings, settings)


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """Provide a temporary directory that is automatically cleaned up."""
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path)


@pytest.fixture
async def app_fixture() -> OpenViper:
    """Provide a fresh OpenViper application instance."""
    app = OpenViper(debug=True)
    return app


@pytest.fixture
async def test_client(app_fixture: OpenViper) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an httpx.AsyncClient for the app."""
    async with app_fixture.test_client() as client:
        yield client


@pytest.fixture
def logger_capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Fixture to capture logs."""
    caplog.set_level(logging.DEBUG)
    return caplog
