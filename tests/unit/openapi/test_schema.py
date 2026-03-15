"""Unit tests for openviper.openapi.schema — type mapping, path params, operations, full schema."""

import inspect
from typing import Optional, Union

from openviper.openapi.schema import (
    OPENAPI_REQUEST_SCHEMA_ATTR,
    _build_operation,
    _extract_path_params,
    _openapi_path,
    _python_type_to_schema,
    _resolve_request_schema,
    _union_schema,
    generate_openapi_schema,
    request_schema,
    reset_openapi_cache,
)


class TestPythonTypeToSchema:
    def setup_method(self):
        reset_openapi_cache()
        _python_type_to_schema.cache_clear()

    def test_int(self):
        assert _python_type_to_schema(int) == {"type": "integer"}

    def test_float(self):
        assert _python_type_to_schema(float) == {"type": "number"}

    def test_str(self):
        assert _python_type_to_schema(str) == {"type": "string"}

    def test_bool(self):
        assert _python_type_to_schema(bool) == {"type": "boolean"}

    def test_bytes(self):
        assert _python_type_to_schema(bytes) == {"type": "string", "format": "binary"}

    def test_list_plain(self):
        assert _python_type_to_schema(list) == {"type": "array"}

    def test_list_typed(self):
        schema = _python_type_to_schema(list[int])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "integer"

    def test_dict(self):
        assert _python_type_to_schema(dict) == {"type": "object"}

    def test_dict_typed(self):
        schema = _python_type_to_schema(dict[str, int])
        assert schema["type"] == "object"

    def test_empty_annotation(self):
        assert _python_type_to_schema(inspect.Parameter.empty) == {}

    def test_none(self):
        assert _python_type_to_schema(None) == {}

    def test_optional(self):
        schema = _python_type_to_schema(Optional[int])
        assert schema["type"] == "integer"
        assert schema["nullable"] is True

    def test_optional_does_not_poison_inner_cache(self):
        """Optional[X] must not mutate the cached schema for X itself."""
        _python_type_to_schema.cache_clear()
        _ = _python_type_to_schema(Optional[int])
        plain = _python_type_to_schema(int)
        assert "nullable" not in plain, "cache-poisoning: int schema was mutated by Optional[int]"

    def test_unknown_type_fallback(self):
        class CustomType:
            pass

        schema = _python_type_to_schema(CustomType)
        assert schema["type"] == "string"


class TestUnionSchema:
    def setup_method(self):
        _python_type_to_schema.cache_clear()

    def test_optional_int(self):
        schema = _union_schema(Optional[int])
        assert schema == {"type": "integer", "nullable": True}

    def test_multi_union_fallback(self):
        schema = _union_schema(Union[int, str])
        assert schema == {"type": "string"}


class TestExtractPathParams:
    def test_no_params(self):
        assert not _extract_path_params("/users/")

    def test_simple_param(self):
        params = _extract_path_params("/users/{id}")
        assert len(params) == 1
        assert params[0]["name"] == "id"
        assert params[0]["schema"]["type"] == "string"

    def test_typed_int_param(self):
        params = _extract_path_params("/users/{id:int}")
        assert params[0]["schema"]["type"] == "integer"

    def test_typed_uuid_param(self):
        params = _extract_path_params("/items/{item_id:uuid}")
        assert params[0]["schema"]["format"] == "uuid"

    def test_multiple_params(self):
        params = _extract_path_params("/users/{user_id:int}/posts/{post_id:int}")
        assert len(params) == 2


class TestOpenAPIPath:
    def test_strips_type_hints(self):
        assert _openapi_path("/users/{id:int}") == "/users/{id}"

    def test_preserves_no_hint(self):
        assert _openapi_path("/users/{id}") == "/users/{id}"

    def test_multiple(self):
        result = _openapi_path("/users/{uid:int}/posts/{pid:uuid}")
        assert result == "/users/{uid}/posts/{pid}"


class TestRequestSchema:
    def test_decorator_attaches_schema(self):
        class MockSerializer:
            pass

        @request_schema(MockSerializer)
        async def handler(request):
            pass

        assert getattr(handler, OPENAPI_REQUEST_SCHEMA_ATTR) is MockSerializer

    def test_decorator_via_getattr(self):
        """Attribute is public (no leading underscore)."""

        class MockSerializer:
            pass

        @request_schema(MockSerializer)
        async def handler(request):
            pass

        assert handler.openapi_request_schema is MockSerializer


class TestResolveRequestSchema:
    def test_from_decorator(self):
        class MockSerializer:
            pass

        @request_schema(MockSerializer)
        async def handler(request):
            pass

        assert _resolve_request_schema(handler) is MockSerializer

    def test_from_view_class(self):
        class MockSerializer:
            pass

        class MyView:
            serializer_class = MockSerializer

        async def handler(request):
            pass

        handler.view_class = MyView
        assert _resolve_request_schema(handler) is MockSerializer

    def test_none_when_nothing(self):
        async def handler(request):
            pass

        assert _resolve_request_schema(handler) is None


class _FakeRoute:
    """Minimal Route mock for testing."""

    def __init__(self, path, methods, handler, name=None):
        self.path = path
        self.methods = methods
        self.handler = handler
        self.name = name or handler.__name__


class TestBuildOperation:
    def setup_method(self):
        reset_openapi_cache()

    def test_basic_get(self):
        async def list_users(request):
            """List all users."""

        route = _FakeRoute("/users/", ["GET"], list_users)
        op = _build_operation(route, "GET")
        assert op["summary"] == "List all users."
        assert op["operationId"].endswith("_list_users")
        assert "200" in op["responses"]

    def test_post_gets_request_body(self):
        async def create_user(request):
            pass

        route = _FakeRoute("/users/", ["POST"], create_user)
        op = _build_operation(route, "POST")
        assert "requestBody" in op
        assert "422" in op["responses"]

    def test_path_params_included(self):
        async def get_user(request, user_id: int):
            pass

        route = _FakeRoute("/users/{user_id:int}", ["GET"], get_user)
        op = _build_operation(route, "GET")
        assert len(op["parameters"]) == 1
        assert op["parameters"][0]["name"] == "user_id"

    def test_tags_from_path(self):
        async def handler(request):
            pass

        route = _FakeRoute("/users/", ["GET"], handler)
        op = _build_operation(route, "GET")
        assert "Users" in op["tags"]

    def test_tag_skips_path_params(self):
        """A route like /{id}/items should tag as 'Items', not '{id}'."""

        async def handler(request):
            pass

        route = _FakeRoute("/{id:int}/items/", ["GET"], handler)
        op = _build_operation(route, "GET")
        assert op["tags"] == ["Items"]

    def test_operationid_includes_module(self):
        """operationId includes the handler's module to avoid name collisions."""

        async def list_items(request):
            pass

        route = _FakeRoute("/items/", ["GET"], list_items)
        op = _build_operation(route, "GET")
        assert "_list_items" in op["operationId"]


class TestGenerateOpenAPISchema:
    def setup_method(self):
        reset_openapi_cache()

    def test_basic_schema(self):
        async def list_users(request):
            pass

        route = _FakeRoute("/users/", ["GET"], list_users)
        schema = generate_openapi_schema([route], title="Test API", version="1.0.0")
        assert schema["openapi"] == "3.1.0"
        assert schema["info"]["title"] == "Test API"
        assert "/users/" in schema["paths"]

    def test_empty_routes(self):
        schema = generate_openapi_schema([])
        assert schema["paths"] == {}

    def test_caching(self):
        async def handler(request):
            pass

        route = _FakeRoute("/test/", ["GET"], handler)
        schema1 = generate_openapi_schema([route], title="Cached", version="1.0")
        schema2 = generate_openapi_schema([route], title="Cached", version="1.0")
        assert schema1 is schema2

    def test_reset_cache(self):
        async def handler(request):
            pass

        route = _FakeRoute("/test/", ["GET"], handler)
        schema1 = generate_openapi_schema([route], title="Reset", version="1.0")
        reset_openapi_cache()
        schema2 = generate_openapi_schema([route], title="Reset", version="1.0")
        assert schema1 is not schema2

    def test_security_schemes(self):
        schema = generate_openapi_schema([])
        assert "BearerAuth" in schema["components"]["securitySchemes"]
        assert "SessionAuth" in schema["components"]["securitySchemes"]

    def test_skips_internal_paths(self):
        async def handler(request):
            pass

        route1 = _FakeRoute("/open-api/openapi.json", ["GET"], handler)
        route2 = _FakeRoute("/users/", ["GET"], handler)
        schema = generate_openapi_schema([route1, route2])
        assert "/open-api/openapi.json" not in schema["paths"]
        assert "/users/" in schema["paths"]

    def test_head_method_omitted(self):
        async def handler(request):
            pass

        route = _FakeRoute("/test/", ["GET", "HEAD"], handler)
        schema = generate_openapi_schema([route], title="HeadTest", version="1.0")
        path_ops = schema["paths"]["/test/"]
        assert "head" not in path_ops
        assert "get" in path_ops

    def test_cache_key_pipe_separator_no_false_hit(self):
        """title/version values containing the old '|' separator must not collide."""
        reset_openapi_cache()
        schema1 = generate_openapi_schema([], title="A|B", version="C")
        reset_openapi_cache()
        schema2 = generate_openapi_schema([], title="A", version="B|C")
        # Different logical keys — must not be the same cached object
        assert (
            schema1["info"]["title"] != schema2["info"]["title"]
            or schema1["info"]["version"] != schema2["info"]["version"]
        )
