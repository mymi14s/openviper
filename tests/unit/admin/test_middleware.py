from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.admin.middleware import (
    AdminMiddleware,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)


class DummyUser:
    def __init__(self, is_authenticated=True, is_staff=False, is_superuser=False):
        self.is_authenticated = is_authenticated
        self.is_staff = is_staff
        self.is_superuser = is_superuser


@pytest.fixture
def mock_app():
    return AsyncMock()


@pytest.fixture
def middleware(mock_app):
    return AdminMiddleware(mock_app)


@pytest.mark.asyncio
async def test_admin_middleware_non_http(middleware, mock_app):
    scope = {"type": "websocket"}
    await middleware(scope, AsyncMock(), AsyncMock())
    mock_app.assert_called_once()


@pytest.mark.asyncio
async def test_admin_middleware_non_admin_path(middleware, mock_app):
    scope = {"type": "http", "path": "/api/users/"}
    await middleware(scope, AsyncMock(), AsyncMock())
    mock_app.assert_called_once()


@pytest.mark.asyncio
async def test_admin_middleware_exempt_path(middleware, mock_app):
    scope = {"type": "http", "path": "/admin/api/auth/login"}
    await middleware(scope, AsyncMock(), AsyncMock())
    mock_app.assert_called_once()

    # Trailing slash test
    mock_app.reset_mock()
    scope = {"type": "http", "path": "/admin/api/config/"}
    await middleware(scope, AsyncMock(), AsyncMock())
    mock_app.assert_called_once()


@pytest.mark.asyncio
async def test_admin_middleware_unauthenticated(middleware, mock_app):
    scope = {"type": "http", "path": "/admin/api/users/"}
    send_mock = AsyncMock()
    await middleware(scope, AsyncMock(), send_mock)

    mock_app.assert_not_called()
    assert send_mock.call_count >= 1
    # Check that a 401 response was sent
    calls = send_mock.call_args_list
    assert any(
        call[0][0]["type"] == "http.response.start" and call[0][0]["status"] == 401
        for call in calls
    )


@pytest.mark.asyncio
async def test_admin_middleware_authenticated_staff(middleware, mock_app):
    scope = {"type": "http", "path": "/admin/api/users/", "user": DummyUser(is_staff=True)}
    await middleware(scope, AsyncMock(), AsyncMock())
    mock_app.assert_called_once()


@pytest.mark.asyncio
async def test_admin_middleware_authenticated_non_staff(middleware, mock_app):
    scope = {
        "type": "http",
        "path": "/admin/api/users/",
        "user": DummyUser(is_authenticated=True, is_staff=False),
    }
    send_mock = AsyncMock()
    await middleware(scope, AsyncMock(), send_mock)
    mock_app.assert_not_called()


@pytest.mark.asyncio
async def test_check_admin_authentication():
    middleware = AdminMiddleware(AsyncMock())

    # No user
    assert await middleware.check_admin_authentication({}) is False

    # Not authenticated
    assert (
        await middleware.check_admin_authentication({"user": DummyUser(is_authenticated=False)})
        is False
    )

    # Authenticated but not staff/superuser
    assert await middleware.check_admin_authentication({"user": DummyUser()}) is False

    # Staff
    assert await middleware.check_admin_authentication({"user": DummyUser(is_staff=True)}) is True

    # Superuser
    assert (
        await middleware.check_admin_authentication({"user": DummyUser(is_superuser=True)}) is True
    )


def test_check_admin_access():
    class RequestMock:
        def __init__(self, user=None):
            self.user = user

    assert check_admin_access(RequestMock()) is False
    assert check_admin_access(RequestMock(DummyUser(is_authenticated=False))) is False
    assert check_admin_access(RequestMock(DummyUser())) is False
    assert check_admin_access(RequestMock(DummyUser(is_staff=True))) is True
    assert check_admin_access(RequestMock(DummyUser(is_superuser=True))) is True


def test_check_model_permission():
    class RequestMock:
        def __init__(self, user=None):
            self.user = user

    assert check_model_permission(RequestMock(), MagicMock(), "view") is False
    assert (
        check_model_permission(RequestMock(DummyUser(is_superuser=True)), MagicMock(), "view")
        is True
    )
    assert (
        check_model_permission(RequestMock(DummyUser(is_staff=True)), MagicMock(), "view") is True
    )
    assert check_model_permission(RequestMock(DummyUser()), MagicMock(), "view") is False


def test_check_object_permission():
    class RequestMock:
        def __init__(self, user=None):
            self.user = user

    assert check_object_permission(RequestMock(), MagicMock(), "change") is False
    assert (
        check_object_permission(RequestMock(DummyUser(is_superuser=True)), MagicMock(), "change")
        is True
    )
    assert (
        check_object_permission(RequestMock(DummyUser(is_staff=True)), MagicMock(), "change")
        is True
    )
    assert check_object_permission(RequestMock(DummyUser()), MagicMock(), "change") is False
