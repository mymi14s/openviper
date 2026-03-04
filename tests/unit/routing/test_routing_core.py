import pytest

from openviper.exceptions import MethodNotAllowed, NotFound
from openviper.http.response import JSONResponse
from openviper.routing.router import Router, include


def test_router_basic_matching():
    router = Router()

    @router.get("/hello")
    async def hello():
        return {"hello": "world"}

    route, params = router.resolve("GET", "/hello")
    assert route is not None
    assert route.path == "/hello"
    assert params == {}

    with pytest.raises(NotFound):
        router.resolve("GET", "/not-found")


def test_router_path_parameters():
    router = Router()

    @router.get("/users/{user_id}")
    async def get_user(user_id: str):
        return {"user_id": user_id}

    route, params = router.resolve("GET", "/users/123")
    assert route is not None
    assert params == {"user_id": "123"}


def test_router_inclusion():
    main_router = Router()
    auth_router = Router()

    @auth_router.post("/login")
    async def login():
        return {"status": "ok"}

    main_router.include_router(include(auth_router, prefix="/auth"))

    route, params = main_router.resolve("POST", "/auth/login")
    assert route is not None
    assert route.path == "/auth/login"


def test_router_method_not_allowed():
    router = Router()

    @router.get("/only-get")
    async def only_get():
        return {"ok": True}

    with pytest.raises(MethodNotAllowed):
        router.resolve("POST", "/only-get")
