import pytest

from openviper.exceptions import MethodNotAllowed, NotFound
from openviper.routing.router import Route, Router, _compile_path, include


async def dummy_handler(request):
    return "ok"


def test_compile_path():
    regex, converters = _compile_path("/users/{id:int}/files/{file:path}")

    assert "id" in converters
    assert "file" in converters
    assert converters["id"] is int
    assert converters["file"] is str

    m = regex.match("/users/123/files/some/folder/img.png")
    assert m is not None
    assert m.group("id") == "123"
    assert m.group("file") == "some/folder/img.png"

    m2 = regex.match("/users/abc/files/img.png")
    assert m2 is None


def test_route_match():
    r = Route("/post/{slug:slug}/{pk:int}", {"GET"}, dummy_handler)

    res = r.match("/post/my-first-post/42")
    assert res == {"slug": "my-first-post", "pk": 42}

    res2 = r.match("/post/invalid!/42")
    assert res2 is None

    rep = repr(r)
    assert "Route" in rep
    assert "'/post/{slug:slug}/{pk:int}'" in rep


def test_router_decorators():
    router = Router(prefix="/api")

    @router.get("/1")
    async def h1(req):
        pass

    @router.post("/2")
    async def h2(req):
        pass

    @router.put("/3")
    async def h3(req):
        pass

    @router.patch("/4")
    async def h4(req):
        pass

    @router.delete("/5")
    async def h5(req):
        pass

    @router.options("/6")
    async def h6(req):
        pass

    @router.any("/7")
    async def h7(req):
        pass

    assert len(router.routes) == 7
    # get adds HEAD
    assert router.routes[0].methods == {"GET", "HEAD"}
    assert router.routes[1].methods == {"POST"}
    assert router.routes[2].methods == {"PUT"}
    assert router.routes[3].methods == {"PATCH"}
    assert router.routes[4].methods == {"DELETE"}
    assert router.routes[5].methods == {"OPTIONS"}
    assert router.routes[6].methods == {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def test_router_add():
    router = Router()
    router.add("/manual", dummy_handler, methods=["POST"], namespace="manual_route")

    assert len(router.routes) == 1
    r = router.routes[0]
    assert r.path == "/manual"
    assert r.methods == {"POST"}
    assert r.name == "manual_route"


def test_router_include_router():
    core = Router()
    core.add("/index", dummy_handler, namespace="index")

    sub = Router(prefix="/api")
    sub.add("/users", dummy_handler, namespace="users")

    core.include_router(sub)

    assert len(core.routes) == 2
    paths = [r.path for r in core.routes]
    assert paths == ["/index", "/api/users"]


def test_router_resolve():
    router = Router()
    router.add("/users", dummy_handler, methods=["GET"], namespace="users")
    router.add("/users/{id:int}", dummy_handler, methods=["GET", "PUT"])

    # Exact match
    route, params = router.resolve("get", "/users")
    assert route.name == "users"
    assert params == {}

    # Slash normalisation (adding trailing)
    route, params = router.resolve("get", "/users/")
    assert route.name == "users"

    # Slash normalisation (removing trailing)
    router.add("/admin/", dummy_handler, methods=["GET"], namespace="admin")
    route, params = router.resolve("get", "/admin")
    assert route.name == "admin"

    # Params match
    route, params = router.resolve("put", "/users/10")
    assert params == {"id": 10}

    # Method not allowed
    with pytest.raises(MethodNotAllowed) as exc:
        router.resolve("post", "/users")
    assert exc.value.headers["Allow"] == "GET"

    # Method not allowed falling back to candidate method collection
    with pytest.raises(MethodNotAllowed) as exc2:
        router.resolve("post", "/users/")
    assert exc2.value.headers["Allow"] == "GET"  # because candidates include /users

    # Not found
    with pytest.raises(NotFound):
        router.resolve("get", "/unknown")

    # Edge case: root "/"
    router.add("/", dummy_handler)
    r, _ = router.resolve("GET", "/")
    assert r.path == "/"


def test_router_url_for():
    router = Router()
    router.add("/users/{id:int}/post/{slug:slug}", dummy_handler, namespace="user_post")

    url = router.url_for("user_post", id=5, slug="hello")
    assert url == "/users/5/post/hello"

    with pytest.raises(KeyError):
        router.url_for("missing")


def test_router_repr():
    r = Router(prefix="/v1")
    assert repr(r) == "Router(prefix='/v1', routes=0)"


def test_include_helper():
    sub = Router()
    sub.add("/action", dummy_handler)

    # Add a nested sub-router
    sub_sub = Router()
    sub_sub.add("/deep", dummy_handler)
    sub.include_router(sub_sub)

    wrapper = include(sub, prefix="/v1")

    assert len(wrapper.routes) == 2
    assert wrapper.routes[0].path == "/v1/action"
    assert wrapper.routes[1].path == "/v1/deep"

    # Return original router if no prefix
    assert include(sub) is sub
