"""Unit tests for View actions."""

from unittest.mock import MagicMock

import pytest

from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.http.views import View, action
from openviper.routing.router import Router


class MockUser:
    id = 123
    username = "testuser"


@pytest.fixture
def request_mock():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.user = MockUser()
    return request


class UserView(View):
    async def get(self, request, **kwargs):
        return JSONResponse({"action": "list"})

    @action(detail=False)
    async def me(self, request, **kwargs):
        return JSONResponse({"action": "me", "user": request.user.username})

    @action(detail=True, methods=["POST"], url_path="deactivate")
    async def deactivate_user(self, request, id, **kwargs):
        return JSONResponse({"action": "deactivate", "id": id})


@pytest.mark.asyncio
async def test_action_registration(request_mock):
    router = Router()
    UserView.register(router, "/users")

    # 1. Verify standard GET
    route, params = router.resolve("GET", "/users")
    assert route.name == "UserView"
    response = await route.handler(request_mock, **params)
    assert response.status_code == 200
    assert response.body == b'{"action":"list"}'

    # 2. Verify @action(detail=False)
    route, params = router.resolve("GET", "/users/me")
    assert route.name == "userview_me"
    response = await route.handler(request_mock, **params)
    assert response.body == b'{"action":"me","user":"testuser"}'

    # 3. Verify @action(detail=True)
    request_mock.method = "POST"
    route, params = router.resolve("POST", "/users/456/deactivate")
    assert route.name == "userview_deactivate_user"
    assert params == {"id": "456"}
    response = await route.handler(request_mock, **params)
    assert response.body == b'{"action":"deactivate","id":"456"}'


@pytest.mark.asyncio
async def test_action_with_existing_pk_placeholder(request_mock):
    router = Router()
    # If the base path already has {id}, it shouldn't be doubled
    UserView.register(router, "/users/{id}")

    route, params = router.resolve("POST", "/users/789/deactivate")
    assert params == {"id": "789"}
    response = await route.handler(request_mock, **params)
    assert response.body == b'{"action":"deactivate","id":"789"}'
