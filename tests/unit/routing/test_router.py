import logging
import time

import pytest

from openviper.exceptions import MethodNotAllowed, NotFound
from openviper.routing.router import Route, Router, _compile_path, _normalize_path, include


async def mock_handler(request):
    return "ok"


# ── Route matching ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_matching_literal():
    route = Route(path="/hello", methods={"GET"}, handler=mock_handler)
    assert route.match("/hello") == {}
    assert route.match("/world") is None


@pytest.mark.asyncio
async def test_route_matching_params():
    route = Route(path="/users/{id:int}", methods={"GET"}, handler=mock_handler)
    assert route.match("/users/123") == {"id": 123}
    assert route.match("/users/abc") is None


@pytest.mark.asyncio
async def test_route_matching_typed_params():
    r_float = Route(path="/p/{v:float}", methods={"GET"}, handler=mock_handler)
    assert r_float.match("/p/1.5") == {"v": 1.5}

    r_uuid = Route(path="/u/{v:uuid}", methods={"GET"}, handler=mock_handler)
    u_str = "550e8400-e29b-41d4-a716-446655440000"
    assert r_uuid.match(f"/u/{u_str}") == {"v": u_str}

    r_path = Route(path="/static/{v:path}", methods={"GET"}, handler=mock_handler)
    assert r_path.match("/static/foo/bar/baz.txt") == {"v": "foo/bar/baz.txt"}


# ── Security: path converter (ReDoS) ─────────────────────────────────────────


def test_path_converter_possessive_no_redos():
    """Possessive quantifier (.++) prevents catastrophic backtracking on path converter.

    Without possessive, a route like /files/{p:path}/suffix forces the engine to
    try every possible split of a long adversarial string before failing.  With
    .++ it fails immediately after one pass.
    """
    # Route with path converter followed by a literal suffix triggers worst-case
    # backtracking with a plain .+ but not with possessive .++.
    route = Route(path="/files/{p:path}/info", methods={"GET"}, handler=mock_handler)
    adversarial = "/files/" + "a/" * 60 + "NOMATCH"
    start = time.monotonic()
    result = route.match(adversarial)
    elapsed = time.monotonic() - start
    assert result is None
    assert elapsed < 0.5, f"match took {elapsed:.3f}s — possible ReDoS"


def test_path_converter_at_end_still_works():
    """path converter at the end of a route works correctly."""
    route = Route(path="/static/{v:path}", methods={"GET"}, handler=mock_handler)
    assert route.match("/static/a/b/c.txt") == {"v": "a/b/c.txt"}
    assert route.match("/static/single") == {"v": "single"}
    assert route.match("/other/a/b") is None


# ── Security: path normalization ─────────────────────────────────────────────


def test_normalize_path_double_slash():
    assert _normalize_path("//users/123") == "/users/123"
    assert _normalize_path("/api//v1//items") == "/api/v1/items"
    assert _normalize_path("///deep") == "/deep"


def test_normalize_path_single_slash_unchanged():
    path = "/users/123"
    assert _normalize_path(path) is path  # fast-path returns same object


def test_normalize_path_root_unchanged():
    assert _normalize_path("/") == "/"


@pytest.mark.asyncio
async def test_router_resolve_double_slash():
    """Consecutive slashes in the request path are collapsed before routing."""
    router = Router()

    @router.get("/users/{id:int}")
    async def get_user(request, id):
        pass

    route, params = router.resolve("GET", "//users/42")
    assert route.handler == get_user
    assert params == {"id": 42}


@pytest.mark.asyncio
async def test_router_resolve_triple_slash():
    router = Router()

    @router.get("/api/v1/items")
    async def items(request):
        pass

    route, _ = router.resolve("GET", "///api///v1///items")
    assert route.handler == items


# ── Router registration & resolution ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_registration():
    router = Router()

    @router.get("/home")
    async def home(request):
        pass

    @router.post("/items/{id:int}")
    async def create_item(request, id):
        pass

    route, params = router.resolve("GET", "/home")
    assert route.handler == home

    route, params = router.resolve("POST", "/items/42")
    assert route.handler == create_item
    assert params == {"id": 42}


@pytest.mark.asyncio
async def test_router_not_found():
    router = Router()
    with pytest.raises(NotFound):
        router.resolve("GET", "/not-found")


@pytest.mark.asyncio
async def test_router_method_not_allowed():
    router = Router()

    @router.get("/only-get")
    async def only_get(request):
        pass

    with pytest.raises(MethodNotAllowed) as exc:
        router.resolve("POST", "/only-get")
    assert "GET" in exc.value.headers["Allow"]


@pytest.mark.asyncio
async def test_router_all_methods():
    router = Router()
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    for m in methods:
        decorator = getattr(router, m.lower())

        @decorator(f"/{m.lower()}")
        async def h(request):
            return "ok"

    for m in methods:
        route, _ = router.resolve(m, f"/{m.lower()}")
        assert m in route.methods


@pytest.mark.asyncio
async def test_router_any_method():
    router = Router()

    @router.any("/any")
    async def any_handler(request):
        pass

    for m in ["GET", "POST", "DELETE"]:
        route, _ = router.resolve(m, "/any")
        assert m in route.methods


@pytest.mark.asyncio
async def test_router_slash_normalization():
    router = Router()

    @router.get("/slash/")
    async def has_slash(request):
        pass

    @router.get("/no-slash")
    async def no_slash(request):
        pass

    route, _ = router.resolve("GET", "/slash")
    assert route.handler == has_slash

    route, _ = router.resolve("GET", "/no-slash/")
    assert route.handler == no_slash


@pytest.mark.asyncio
async def test_router_dynamic_first_segment():
    router = Router()

    @router.get("/{param}/foo")
    async def dynamic_start(request, param):
        pass

    route, params = router.resolve("GET", "/val/foo")
    assert route.handler == dynamic_start
    assert params == {"param": "val"}


@pytest.mark.asyncio
async def test_router_add_direct():
    router = Router()

    async def direct_h(request):
        pass

    router.add("/direct", direct_h, methods=["POST"])
    route, _ = router.resolve("POST", "/direct")
    assert route.handler == direct_h


# ── allowed_methods correctness ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_methods_specific_route_wins():
    """Exact route with GET + catch-all with DELETE: DELETE /exact succeeds via catch-all."""
    router = Router()

    @router.get("/users")
    async def list_users(request):
        pass

    @router.delete("/{resource}")
    async def catch_all_delete(request, resource):
        pass

    # DELETE /users should route to the catch-all (it matches the path and method)
    route, params = router.resolve("DELETE", "/users")
    assert route.handler == catch_all_delete
    assert params == {"resource": "users"}


@pytest.mark.asyncio
async def test_allowed_methods_includes_all_path_matching_routes():
    """MethodNotAllowed allowed list reflects every route whose path matched."""
    router = Router()

    @router.get("/users")
    async def list_users(request):
        pass

    @router.put("/{resource}")
    async def update_any(request, resource):
        pass

    # PATCH /users: neither route supports PATCH, but both match the path
    with pytest.raises(MethodNotAllowed) as exc:
        router.resolve("PATCH", "/users")
    allowed = exc.value.headers["Allow"]
    assert "GET" in allowed
    assert "PUT" in allowed


# ── url_for ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_path_cache():
    p1, c1 = _compile_path("/foo/{id:int}")
    p2, c2 = _compile_path("/foo/{id:int}")
    assert p1 is p2  # same compiled object from lru_cache


@pytest.mark.asyncio
async def test_router_url_for_errors():
    router = Router()
    with pytest.raises(KeyError):
        router.url_for("non_existent")


@pytest.mark.asyncio
async def test_url_for_no_type():
    router = Router()

    @router.get("/foo/{param}", name="test")
    async def foo(request, param):
        pass

    assert router.url_for("test", param="bar") == "/foo/bar"


@pytest.mark.asyncio
async def test_url_for_typed_params():
    """url_for single-pass re.sub handles {name:type} placeholders."""
    router = Router()

    @router.get("/users/{id:int}/posts/{slug:slug}", name="user_post")
    async def user_post(request, id, slug):
        pass

    assert router.url_for("user_post", id=42, slug="hello-world") == "/users/42/posts/hello-world"


@pytest.mark.asyncio
async def test_url_for_unresolved_placeholder_preserved():
    """Placeholders with no matching kwarg are left as-is."""
    router = Router()

    @router.get("/a/{x}/b/{y:int}", name="two_params")
    async def two(request, x, y):
        pass

    result = router.url_for("two_params", x="foo")
    assert result == "/a/foo/b/{y:int}"


@pytest.mark.asyncio
async def test_url_for_float_and_uuid():
    router = Router()

    @router.get("/data/{value:float}", name="data")
    async def data(request, value):
        pass

    assert router.url_for("data", value=3.14) == "/data/3.14"


# ── Sub-routers ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_sub_router_nested_prefix():
    root = Router(prefix="/api")
    v1 = Router(prefix="/v1")
    users = Router(prefix="/users")

    @users.get("/{id:int}")
    async def get_user(request, id):
        pass

    v1.include_router(users)
    root.include_router(v1)

    route, params = root.resolve("GET", "/api/v1/users/123")
    assert route.handler == get_user
    assert params == {"id": 123}


@pytest.mark.asyncio
async def test_include_helper():
    child = Router(prefix="/child")

    @child.get("/hi")
    async def hi(request):
        pass

    wrapped = include(child, prefix="/parent")
    assert wrapped.prefix == "/parent/child"

    route = wrapped.routes[0]
    assert route.path == "/parent/child/hi"


# ── Misc ──────────────────────────────────────────────────────────────────────


def test_router_repr():
    router = Router(prefix="/test")
    assert "/test" in repr(router)


# ── Security: int/float converter digit cap ───────────────────────────────────


def test_int_converter_rejects_overlong():
    """int converter must not match more than 18 digits (prevents huge int allocation)."""
    route = Route(path="/users/{user_id:int}", methods={"GET"}, handler=mock_handler)
    assert route.match("/users/" + "9" * 18) is not None  # 18 digits: OK
    assert route.match("/users/" + "9" * 19) is None  # 19 digits: rejected


def test_float_converter_rejects_overlong_integer_part():
    """float converter caps integer part at 18 digits."""
    route = Route(path="/v/{v:float}", methods={"GET"}, handler=mock_handler)
    assert route.match("/v/" + "9" * 18) is not None
    assert route.match("/v/" + "9" * 19) is None


def test_float_converter_rejects_overlong_decimal_part():
    """float converter caps decimal part at 18 digits."""
    route = Route(path="/v/{v:float}", methods={"GET"}, handler=mock_handler)
    assert route.match("/v/1." + "9" * 18) is not None
    assert route.match("/v/1." + "9" * 19) is None


# ── Security: parameter name validation ──────────────────────────────────────


def test_route_rejects_numeric_param_name():
    """Parameter names starting with a digit must raise ValueError at registration."""
    with pytest.raises(ValueError, match="Invalid path parameter name"):
        Route(path="/items/{123:int}", methods={"GET"}, handler=mock_handler)


def test_route_rejects_hyphen_in_param_name():
    """Parameter names containing hyphens must raise ValueError at registration."""
    with pytest.raises(ValueError, match="Invalid path parameter name"):
        Route(path="/items/{a-b}", methods={"GET"}, handler=mock_handler)


def test_route_accepts_valid_param_names():
    """Valid Python-identifier parameter names must not raise."""
    route = Route(path="/items/{item_id:int}", methods={"GET"}, handler=mock_handler)
    assert route.match("/items/42") == {"item_id": 42}

    route2 = Route(path="/{_private}/data", methods={"GET"}, handler=mock_handler)
    assert route2.match("/secret/data") == {"_private": "secret"}


# ── Correctness: duplicate route name warning ─────────────────────────────────


def test_duplicate_route_name_warns(caplog):
    """Registering two routes with the same name must emit a warning and use the later one."""
    router = Router()

    @router.get("/users", name="list")
    async def users(request):
        pass

    @router.get("/admins", name="list")
    async def admins(request):
        pass

    with caplog.at_level(logging.WARNING, logger="openviper.routing.router"):
        _ = router.routes  # trigger index build

    assert any("list" in record.message and "shadow" in record.message for record in caplog.records)
    # url_for resolves to the later route
    assert router.url_for("list") == "/admins"


def test_unique_route_names_no_warning(caplog):
    """Unique route names must not emit any duplicate-name warnings."""
    router = Router()

    @router.get("/users", name="users")
    async def users(request):
        pass

    @router.get("/admins", name="admins")
    async def admins(request):
        pass

    with caplog.at_level(logging.WARNING, logger="openviper.routing.router"):
        _ = router.routes

    assert not any("shadow" in record.message for record in caplog.records)


def test_candidate_routes_triggers_lazy_index_build():
    """Calling _candidate_routes() directly on a fresh router triggers lazy build."""
    router = Router()

    @router.get("/resource/{id}")
    async def get_resource(request):
        return "ok"

    # _index must be None before the call
    assert router._index is None
    list(router._candidate_routes("/resource/99"))
    # After the call, index was built
    assert router._index is not None


# ── Exact index: multi-method fast-path ───────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_index_resolves_all_methods_on_same_literal_path():
    """GET and POST registered on the same literal path must both resolve via the fast path."""
    router = Router()

    @router.get("/items")
    async def list_items(request):
        pass

    @router.post("/items")
    async def create_item(request):
        pass

    get_route, _ = router.resolve("GET", "/items")
    post_route, _ = router.resolve("POST", "/items")

    assert get_route.handler == list_items
    assert post_route.handler == create_item


@pytest.mark.asyncio
async def test_exact_index_method_not_allowed_on_literal_path():
    """MethodNotAllowed on a multi-method literal path lists all registered methods."""
    router = Router()

    @router.get("/things")
    async def list_things(request):
        pass

    @router.post("/things")
    async def create_thing(request):
        pass

    with pytest.raises(MethodNotAllowed) as exc:
        router.resolve("DELETE", "/things")

    allowed = exc.value.headers["Allow"]
    assert "GET" in allowed
    assert "POST" in allowed


# ── include() tag propagation ─────────────────────────────────────────────────


def test_include_propagates_tags():
    """include() must copy the source router's tags onto the wrapper router."""
    child = Router(prefix="/v1", tags=["v1"])

    @child.get("/ping")
    async def ping(request):
        pass

    wrapped = include(child, prefix="/api")
    assert wrapped.tags == ["v1"]


def test_include_no_prefix_returns_original_router():
    """include() with no prefix must return the original router unchanged."""
    child = Router(prefix="/child", tags=["original"])
    result = include(child)
    assert result is child
    assert result.tags == ["original"]


# ── Namespace support ─────────────────────────────────────────────────────────


def test_router_namespace_prefixes_route_names():
    """Routes in a namespaced sub-router are accessible via \"namespace:name\"."""
    root = Router(prefix="/api")
    users = Router(prefix="/users", namespace="users")

    @users.get("/me", name="me")
    async def me(request):
        pass

    root.include_router(users)

    assert root.url_for("users:me") == "/api/users/me"


def test_router_namespace_via_include_router_kwarg():
    """namespace kwarg on include_router() sets the sub-router's namespace."""
    root = Router()
    sub = Router(prefix="/items")

    @sub.get("/{id:int}", name="detail")
    async def detail(request, id):
        pass

    root.include_router(sub, namespace="shop")

    assert root.url_for("shop:detail") == "/items/{id:int}"


def test_router_namespace_via_include_helper():
    """namespace kwarg on include() helper is propagated."""
    child = Router(prefix="/orders")

    @child.get("/", name="list")
    async def list_orders(request):
        pass

    root = Router()
    root.include_router(include(child, namespace="orders"))

    assert root.url_for("orders:list") == "/orders/"


def test_namespaced_url_for_with_path_params():
    """url_for on a namespaced route fills path parameter placeholders."""
    root = Router()
    posts = Router(prefix="/posts", namespace="blog")

    @posts.get("/{slug:slug}", name="detail")
    async def detail(request, slug):
        pass

    root.include_router(posts)

    assert root.url_for("blog:detail", slug="hello") == "/posts/hello"


def test_nested_namespace_chains():
    """Nested namespaced routers produce \"outer:inner:name\" route names."""
    root = Router()
    v1 = Router(prefix="/v1", namespace="v1")
    articles = Router(prefix="/articles", namespace="articles")

    @articles.get("/", name="list")
    async def list_articles(request):
        pass

    v1.include_router(articles)
    root.include_router(v1)

    assert root.url_for("v1:articles:list") == "/v1/articles/"


def test_non_namespaced_routes_unaffected():
    """Routes registered without a namespace remain accessible by bare name."""
    root = Router()

    @root.get("/health", name="health")
    async def health(request):
        pass

    namespaced = Router(prefix="/users", namespace="users")

    @namespaced.get("/", name="list")
    async def list_users(request):
        pass

    root.include_router(namespaced)

    assert root.url_for("health") == "/health"
    assert root.url_for("users:list") == "/users/"
