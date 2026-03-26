from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.exceptions import PermissionDenied
from openviper.http.permissions import (
    AllowAny,
    BasePermission,
    IsAdmin,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from openviper.http.views import View


class MockUser:
    def __init__(self, is_authenticated=True, is_staff=False, is_superuser=False):
        self.is_authenticated = is_authenticated
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        self.has_role = AsyncMock(return_value=False)
        self.has_perm = AsyncMock(return_value=False)


class MockRequest:
    def __init__(self, method="GET", user=None):
        self.method = method
        self.user = user


@pytest.mark.asyncio
async def test_base_permissions():
    request = MockRequest()
    view = View()

    assert await AllowAny().has_permission(request, view) is True

    # IsAuthenticated
    assert await IsAuthenticated().has_permission(request, View()) is False
    request.user = MockUser(is_authenticated=True)
    assert await IsAuthenticated().has_permission(request, View()) is True

    # IsAdmin
    assert await IsAdmin().has_permission(request, View()) is False
    request.user = MockUser(is_authenticated=True, is_staff=True)
    assert await IsAdmin().has_permission(request, View()) is True


@pytest.mark.asyncio
async def test_is_authenticated_or_read_only():
    view = View()

    # Anonymous GET allowed
    request = MockRequest(method="GET", user=None)
    assert await IsAuthenticatedOrReadOnly().has_permission(request, view) is True

    # Anonymous POST denied
    request = MockRequest(method="POST", user=None)
    assert await IsAuthenticatedOrReadOnly().has_permission(request, view) is False

    # Authenticated POST allowed
    request.user = MockUser(is_authenticated=True)
    assert await IsAuthenticatedOrReadOnly().has_permission(request, view) is True


@pytest.mark.asyncio
async def test_bitwise_permissions():
    view = View()
    user = MockUser(is_authenticated=True)
    request = MockRequest(user=user)

    # OR
    perm = IsAdmin | IsAuthenticated
    # User is authenticated but NOT admin -> should be True because of OR
    assert await perm().has_permission(request, view) is True

    # AND
    perm = IsAdmin & IsAuthenticated
    # User is authenticated but NOT admin -> should be False because of AND
    assert await perm().has_permission(request, view) is False

    # NOT
    perm = ~IsAdmin
    assert await perm().has_permission(request, view) is True


@pytest.mark.asyncio
async def test_view_check_object_permissions():
    class CustomPermission(BasePermission):
        async def has_permission(self, request, view):
            return True

        async def has_object_permission(self, request, view, obj):
            return obj.get("owner") == request.user.username

    view = View()
    view.permission_classes = [CustomPermission]

    user = MagicMock()
    user.username = "alice"
    request = MockRequest(user=user)

    # Owner matches
    await view.check_object_permissions(request, {"owner": "alice"})

    # Owner mismatch
    with pytest.raises(PermissionDenied):
        await view.check_object_permissions(request, {"owner": "bob"})
