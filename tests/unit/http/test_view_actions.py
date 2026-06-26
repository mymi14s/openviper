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
    authentication_classes = []
    permission_classes = []

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


def test_router_add_class_view_matches_register_route_shapes() -> None:
    register_router = Router()
    add_router = Router()

    UserView.register(register_router, "/users")
    add_router.add("/users", UserView.as_view(), namespace="UserView")

    register_routes = {(route.path, frozenset(route.methods)) for route in register_router.routes}
    add_routes = {(route.path, frozenset(route.methods)) for route in add_router.routes}

    assert add_routes == register_routes


def test_router_add_and_register_match_inferred_detail_paths() -> None:
    class ScoreView(View):
        authentication_classes = []
        permission_classes = []

        async def post(self, request, **kwargs):
            return JSONResponse({"action": "create"})

        async def get(self, request, id: int, **kwargs):
            return JSONResponse({"action": "retrieve", "id": id})

    register_router = Router()
    add_router = Router()

    ScoreView.register(register_router, "/scores")
    add_router.add("/scores", ScoreView.as_view(), namespace="ScoreView")

    register_routes = {(route.path, frozenset(route.methods)) for route in register_router.routes}
    add_routes = {(route.path, frozenset(route.methods)) for route in add_router.routes}

    assert add_routes == register_routes
    assert ("/scores", frozenset({"POST", "OPTIONS"})) in add_routes
    assert ("/scores/{id:int}", frozenset({"GET", "OPTIONS"})) in add_routes
