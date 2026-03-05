"""Integration tests for openviper.openapi.schema (type conversion, extraction, generation)."""

from __future__ import annotations

from openviper.openapi.schema import (
    _extract_path_params,
    _openapi_path,
    _python_type_to_schema,
    _resolve_request_schema,
    request_schema,
)

# ---------------------------------------------------------------------------
# _python_type_to_schema
# ---------------------------------------------------------------------------


class TestPythonTypeToSchema:
    def test_int(self):
        result = _python_type_to_schema(int)
        assert result == {"type": "integer"}

    def test_str(self):
        result = _python_type_to_schema(str)
        assert result == {"type": "string"}

    def test_bool(self):
        result = _python_type_to_schema(bool)
        assert result == {"type": "boolean"}

    def test_float(self):
        result = _python_type_to_schema(float)
        assert result == {"type": "number"}

    def test_bytes(self):
        result = _python_type_to_schema(bytes)
        assert result["type"] == "string"
        assert result.get("format") == "binary"

    def test_list(self):
        result = _python_type_to_schema(list)
        assert result["type"] == "array"

    def test_dict(self):
        result = _python_type_to_schema(dict)
        assert result == {"type": "object"}

    def test_list_of_int(self):
        result = _python_type_to_schema(list[int])
        assert result["type"] == "array"
        assert result["items"] == {"type": "integer"}

    def test_list_of_str(self):
        result = _python_type_to_schema(list[str])
        assert result["type"] == "array"
        assert result["items"] == {"type": "string"}

    def test_optional_int(self):
        result = _python_type_to_schema(int | None)
        assert result["type"] == "integer"
        assert result.get("nullable") is True

    def test_optional_str(self):
        result = _python_type_to_schema(str | None)
        assert result["type"] == "string"
        assert result.get("nullable") is True

    def test_empty_is_empty_dict(self):
        import inspect

        result = _python_type_to_schema(inspect.Parameter.empty)
        assert result == {}

    def test_none_annotation(self):
        result = _python_type_to_schema(None)
        assert result == {}

    def test_unknown_type_fallback(self):
        class CustomClass:
            pass

        result = _python_type_to_schema(CustomClass)
        assert result == {"type": "string"}

    def test_pydantic_model_uses_schema(self):
        from openviper.serializers import Serializer

        class MySchema(Serializer):
            name: str
            age: int

        result = _python_type_to_schema(MySchema)
        # Should use Pydantic's model_json_schema
        assert "properties" in result or "title" in result


# ---------------------------------------------------------------------------
# _extract_path_params
# ---------------------------------------------------------------------------


class TestExtractPathParams:
    def test_no_params(self):
        result = _extract_path_params("/users/")
        assert result == []

    def test_single_int_param(self):
        result = _extract_path_params("/users/{id:int}/")
        assert len(result) == 1
        assert result[0]["name"] == "id"
        assert result[0]["in"] == "path"
        assert result[0]["required"] is True
        assert result[0]["schema"]["type"] == "integer"

    def test_single_str_param(self):
        result = _extract_path_params("/items/{slug}/")
        assert len(result) == 1
        assert result[0]["name"] == "slug"
        assert result[0]["schema"]["type"] == "string"

    def test_multiple_params(self):
        result = _extract_path_params("/app/{app_label:str}/{model_name:str}/")
        assert len(result) == 2
        assert result[0]["name"] == "app_label"
        assert result[1]["name"] == "model_name"

    def test_uuid_param(self):
        result = _extract_path_params("/resources/{uid:uuid}/")
        assert len(result) == 1
        assert result[0]["schema"]["format"] == "uuid"

    def test_float_param(self):
        result = _extract_path_params("/coords/{lat:float}/")
        assert len(result) == 1
        assert result[0]["schema"]["type"] == "number"

    def test_path_param_type(self):
        result = _extract_path_params("/files/{file_path:path}")
        assert len(result) == 1
        assert result[0]["schema"]["type"] == "string"


# ---------------------------------------------------------------------------
# _openapi_path
# ---------------------------------------------------------------------------


class TestOpenApiPath:
    def test_simple_path_unchanged(self):
        assert _openapi_path("/users/") == "/users/"

    def test_int_param_stripped(self):
        result = _openapi_path("/users/{id:int}/")
        assert result == "/users/{id}/"

    def test_str_param_stripped(self):
        result = _openapi_path("/posts/{slug:str}/")
        assert result == "/posts/{slug}/"

    def test_multiple_params(self):
        result = _openapi_path("/apps/{app:str}/{model:str}/{id:int}/")
        assert result == "/apps/{app}/{model}/{id}/"

    def test_no_type_annotation(self):
        result = _openapi_path("/search/{query}/")
        assert result == "/search/{query}/"


# ---------------------------------------------------------------------------
# request_schema decorator
# ---------------------------------------------------------------------------


class TestRequestSchema:
    def test_decorator_attaches_schema_to_handler(self):
        from openviper.serializers import Serializer

        class MyRequestSerializer(Serializer):
            title: str

        @request_schema(MyRequestSerializer)
        async def my_handler(request):
            pass

        assert hasattr(my_handler, "_request_schema")
        assert my_handler._request_schema is MyRequestSerializer

    def test_decorator_returns_original_function(self):
        from openviper.serializers import Serializer

        class TitleSerializer(Serializer):
            title: str

        @request_schema(TitleSerializer)
        async def create_view(request):
            """Create something."""
            pass

        assert create_view.__name__ == "create_view"


# ---------------------------------------------------------------------------
# _resolve_request_schema
# ---------------------------------------------------------------------------


class TestResolveRequestSchema:
    def test_explicit_decorator_takes_priority(self):
        from openviper.serializers import Serializer

        class ExplicitSerializer(Serializer):
            name: str

        async def my_handler(request):
            pass

        my_handler._request_schema = ExplicitSerializer
        result = _resolve_request_schema(my_handler)
        assert result is ExplicitSerializer

    def test_no_schema_returns_none(self):
        async def bare_handler(request):
            pass

        result = _resolve_request_schema(bare_handler)
        assert result is None

    def test_view_class_serializer_class(self):
        from openviper.serializers import Serializer

        class ViewSerializer(Serializer):
            title: str

        class MyView:
            serializer_class = ViewSerializer

        async def view_handler(request):
            pass

        view_handler.view_class = MyView
        result = _resolve_request_schema(view_handler)
        assert result is ViewSerializer


# ---------------------------------------------------------------------------
# generate_openapi (full schema generation)
# ---------------------------------------------------------------------------


class TestGenerateOpenApi:
    def test_generate_basic_schema(self):
        from openviper.openapi.schema import generate_openapi_schema
        from openviper.routing.router import Router

        router = Router()

        @router.get("/health/")
        async def health_check(request):
            """Health check endpoint."""
            pass

        schema = generate_openapi_schema(router.routes, title="Test API", version="0.1.0")
        assert schema["openapi"].startswith("3.")
        assert schema["info"]["title"] == "Test API"
        assert "paths" in schema

    def test_schema_includes_path(self):
        from openviper.openapi.schema import generate_openapi_schema
        from openviper.routing.router import Router

        router = Router()

        @router.get("/users/")
        async def list_users(request):
            """List all users."""
            pass

        schema = generate_openapi_schema(router.routes, title="My API", version="1.0.0")
        assert "/users/" in schema["paths"]

    def test_schema_with_path_params(self):
        from openviper.openapi.schema import generate_openapi_schema
        from openviper.routing.router import Router

        router = Router()

        @router.get("/users/{user_id:int}/")
        async def get_user(request, user_id: int):
            """Get a user by ID."""
            pass

        schema = generate_openapi_schema(router.routes, title="API", version="1.0")
        assert "/users/{user_id}/" in schema["paths"]

    def test_schema_with_post_method(self):
        from openviper.openapi.schema import generate_openapi_schema
        from openviper.routing.router import Router

        router = Router()

        @router.post("/users/")
        async def create_user(request):
            """Create a new user."""
            pass

        schema = generate_openapi_schema(router.routes, title="API", version="1.0")
        path_ops = schema["paths"].get("/users/", {})
        assert "post" in path_ops

    def test_schema_with_request_schema_decorator(self):
        from openviper.openapi.schema import generate_openapi_schema
        from openviper.routing.router import Router
        from openviper.serializers import Serializer

        class CreateUserSerializer(Serializer):
            username: str
            email: str

        router = Router()

        @router.post("/users/")
        @request_schema(CreateUserSerializer)
        async def create_user(request):
            """Create a user."""
            pass

        schema = generate_openapi_schema(router.routes, title="API", version="1.0")
        path_ops = schema["paths"].get("/users/", {})
        post_op = path_ops.get("post", {})
        assert "requestBody" in post_op
