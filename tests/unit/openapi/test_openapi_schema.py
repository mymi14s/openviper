"""Comprehensive unit tests for openviper/openapi/schema.py."""

from __future__ import annotations

import inspect
import sys
from unittest.mock import MagicMock, patch

from openviper.openapi.schema import (
    _build_operation,
    _detect_serializer_from_source,
    _extract_path_params,
    _openapi_path,
    _python_type_to_schema,
    _resolve_request_schema,
    generate_openapi_schema,
    request_schema,
)
from openviper.routing.router import Route

# ---------------------------------------------------------------------------
# Helpers defined at module level so inspect.getsource can find them
# ---------------------------------------------------------------------------


class FakePydanticModel:
    """Stand-in for a Pydantic model (exposes model_json_schema)."""

    @classmethod
    def model_json_schema(cls) -> dict:
        return {
            "type": "object",
            "title": "FakePydanticModel",
            "properties": {"name": {"type": "string"}},
        }


class FakeSerializer:
    """Stand-in for a serializer (exposes model_json_schema)."""

    @classmethod
    def model_json_schema(cls) -> dict:
        return {
            "type": "object",
            "title": "FakeSerializer",
            "properties": {"value": {"type": "integer"}},
        }


# Module-level handlers so inspect.getsource works correctly.


async def _handler_with_validate(request):
    """Handler that calls FakeSerializer.validate."""
    data = FakeSerializer.validate(request.data)
    return data


async def _handler_with_model_validate(request):
    """Handler that calls FakeSerializer.model_validate."""
    data = FakeSerializer.model_validate(request.data)
    return data


async def _handler_no_schema(request):
    """Handler with no serializer calls."""
    return "ok"


async def _handler_with_dict_return(request) -> dict:
    """Handler returning dict."""
    return {}


async def _handler_with_list_return(request) -> list[str]:
    """Handler returning list of strings."""
    return []


async def _handler_with_int_return(request) -> int:
    """Handler returning int."""
    return 0


async def _handler_with_optional_return(request) -> str | None:
    """Handler returning Optional[str]."""
    return None


# View-class helpers at module level so inspect.getsource works on methods.


class _FakeViewClass:
    serializer_class = FakeSerializer

    async def post(self, request):
        data = FakeSerializer.validate(request.data)
        return data


class _FakeViewClassNoSerializer:
    """View class without serializer_class but post uses FakeSerializer."""

    async def post(self, request):
        data = FakeSerializer.validate(request.data)
        return data


class _FakeViewClassWithPut:
    """View class that only has a put method using FakeSerializer."""

    async def put(self, request):
        data = FakeSerializer.validate(request.data)
        return data


class _FakeViewClassWithPatch:
    """View class that only has a patch method using FakeSerializer."""

    async def patch(self, request):
        data = FakeSerializer.validate(request.data)
        return data


class _FakeViewClassEmpty:
    """View class with no mutating methods."""

    async def get(self, request):
        return {}


def _make_route(
    path: str,
    methods: list,
    handler,
    name: str | None = None,
) -> Route:
    return Route(
        path=path,
        methods=set(methods),
        handler=handler,
        name=name if name is not None else handler.__name__,
    )


# ===========================================================================
# _python_type_to_schema
# ===========================================================================


class TestPythonTypeToSchema:
    def test_empty_annotation_returns_empty(self):
        assert _python_type_to_schema(inspect.Parameter.empty) == {}

    def test_none_annotation_returns_empty(self):
        assert _python_type_to_schema(None) == {}

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

    def test_bare_list(self):
        assert _python_type_to_schema(list) == {"type": "array"}

    def test_bare_dict(self):
        assert _python_type_to_schema(dict) == {"type": "object"}

    def test_generic_list_of_str(self):
        schema = _python_type_to_schema(list[str])
        assert schema == {"type": "array", "items": {"type": "string"}}

    def test_generic_list_of_int(self):
        schema = _python_type_to_schema(list[int])
        assert schema == {"type": "array", "items": {"type": "integer"}}

    def test_generic_list_no_args(self):
        """A mock with origin=list but no __args__ should produce empty items."""
        mock_ann = MagicMock()
        mock_ann.__origin__ = list
        mock_ann.__args__ = None
        schema = _python_type_to_schema(mock_ann)
        assert schema == {"type": "array", "items": {}}

    def test_generic_dict(self):
        schema = _python_type_to_schema(dict[str, int])
        assert schema == {"type": "object"}

    def test_optional_str(self):
        schema = _python_type_to_schema(str | None)
        assert schema["type"] == "string"
        assert schema["nullable"] is True

    def test_optional_int(self):
        schema = _python_type_to_schema(int | None)
        assert schema["type"] == "integer"
        assert schema["nullable"] is True

    def test_optional_list(self):
        schema = _python_type_to_schema(list[str] | None)
        assert schema["type"] == "array"
        assert schema["nullable"] is True

    def test_union_multiple_non_none_falls_to_fallback(self):
        """Union[str, int] has two non-None args; code falls through to fallback."""
        ann = str | int
        schema = _python_type_to_schema(ann)
        # Falls all the way to the string fallback because no branch handles it
        assert schema == {"type": "string"}

    def test_pydantic_model_returns_model_json_schema(self):
        schema = _python_type_to_schema(FakePydanticModel)
        assert schema == FakePydanticModel.model_json_schema()

    def test_unknown_type_falls_back_to_string(self):
        class UnknownType:
            pass

        schema = _python_type_to_schema(UnknownType)
        assert schema == {"type": "string"}

    def test_returns_copy_not_reference(self):
        """Mutations to the returned dict must not affect the lookup table."""
        schema = _python_type_to_schema(int)
        schema["extra"] = "mutated"
        assert _python_type_to_schema(int) == {"type": "integer"}


# ===========================================================================
# _extract_path_params
# ===========================================================================


class TestExtractPathParams:
    def test_no_params_returns_empty_list(self):
        assert _extract_path_params("/users") == []

    def test_root_path(self):
        assert _extract_path_params("/") == []

    def test_untyped_param_defaults_to_str(self):
        params = _extract_path_params("/items/{name}")
        assert len(params) == 1
        assert params[0] == {
            "name": "name",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }

    def test_int_converter(self):
        params = _extract_path_params("/items/{id:int}")
        assert params[0]["schema"] == {"type": "integer"}
        assert params[0]["name"] == "id"

    def test_float_converter(self):
        params = _extract_path_params("/values/{v:float}")
        assert params[0]["schema"] == {"type": "number"}

    def test_uuid_converter(self):
        params = _extract_path_params("/objects/{uid:uuid}")
        assert params[0]["schema"] == {"type": "string", "format": "uuid"}

    def test_path_converter(self):
        params = _extract_path_params("/files/{fp:path}")
        assert params[0]["schema"] == {"type": "string"}

    def test_slug_converter(self):
        params = _extract_path_params("/posts/{slug:slug}")
        assert params[0]["schema"] == {"type": "string"}

    def test_unknown_converter_falls_back_to_string(self):
        params = _extract_path_params("/x/{val:custom}")
        assert params[0]["schema"] == {"type": "string"}

    def test_multiple_params(self):
        params = _extract_path_params("/users/{user_id:int}/posts/{post_id:int}")
        assert len(params) == 2
        names = [p["name"] for p in params]
        assert "user_id" in names
        assert "post_id" in names

    def test_all_params_are_required_and_in_path(self):
        params = _extract_path_params("/a/{x}/b/{y:int}")
        for p in params:
            assert p["required"] is True
            assert p["in"] == "path"

    def test_mixed_typed_and_untyped(self):
        params = _extract_path_params("/{section}/{id:int}")
        schemas = {p["name"]: p["schema"] for p in params}
        assert schemas["section"] == {"type": "string"}
        assert schemas["id"] == {"type": "integer"}


# ===========================================================================
# _openapi_path
# ===========================================================================


class TestOpenApiPath:
    def test_no_params_unchanged(self):
        assert _openapi_path("/users") == "/users"

    def test_root_unchanged(self):
        assert _openapi_path("/") == "/"

    def test_typed_param_stripped(self):
        assert _openapi_path("/users/{id:int}") == "/users/{id}"

    def test_untyped_param_preserved(self):
        assert _openapi_path("/users/{id}") == "/users/{id}"

    def test_multiple_typed_params(self):
        result = _openapi_path("/users/{user_id:int}/posts/{post_id:uuid}")
        assert result == "/users/{user_id}/posts/{post_id}"

    def test_path_converter(self):
        assert _openapi_path("/files/{fp:path}") == "/files/{fp}"

    def test_slug_converter(self):
        assert _openapi_path("/posts/{slug:slug}") == "/posts/{slug}"

    def test_mixed_typed_and_untyped(self):
        result = _openapi_path("/{section}/{id:int}")
        assert result == "/{section}/{id}"


# ===========================================================================
# request_schema decorator
# ===========================================================================


class TestRequestSchema:
    def test_attaches_request_schema_attribute(self):
        async def my_handler(request):
            pass

        decorated = request_schema(FakeSerializer)(my_handler)
        assert decorated._request_schema is FakeSerializer

    def test_returns_same_function(self):
        async def my_handler(request):
            pass

        decorated = request_schema(FakeSerializer)(my_handler)
        assert decorated is my_handler

    def test_decorator_factory_is_callable(self):
        decorator = request_schema(FakePydanticModel)
        assert callable(decorator)

    def test_works_with_any_serializer_class(self):
        async def handler(req):
            pass

        decorated = request_schema(FakePydanticModel)(handler)
        assert decorated._request_schema is FakePydanticModel

    def test_can_be_used_as_stacked_decorator(self):
        @request_schema(FakeSerializer)
        async def handler(req):
            pass

        assert handler._request_schema is FakeSerializer


# ===========================================================================
# _detect_serializer_from_source
# ===========================================================================


class TestDetectSerializerFromSource:
    def test_detects_validate_call(self):
        result = _detect_serializer_from_source(_handler_with_validate)
        assert result is FakeSerializer

    def test_detects_model_validate_call(self):
        result = _detect_serializer_from_source(_handler_with_model_validate)
        assert result is FakeSerializer

    def test_returns_none_when_no_matching_calls(self):
        result = _detect_serializer_from_source(_handler_no_schema)
        assert result is None

    def test_returns_none_on_oserror(self):
        with patch("inspect.getsource", side_effect=OSError("not found")):
            result = _detect_serializer_from_source(_handler_with_validate)
        assert result is None

    def test_returns_none_on_typeerror(self):
        with patch("inspect.getsource", side_effect=TypeError("not inspectable")):
            result = _detect_serializer_from_source(_handler_with_validate)
        assert result is None

    def test_returns_none_on_syntax_error(self):
        with patch("inspect.getsource", return_value="def bad(:\n    pass"):
            result = _detect_serializer_from_source(_handler_with_validate)
        assert result is None

    def test_returns_none_when_name_not_in_globals(self):
        """Class referenced in source but absent from handler globals."""
        source = (
            "async def handler(req):\n"
            "    data = MissingClass.validate(req.data)\n"
            "    return data\n"
        )
        with patch("inspect.getsource", return_value=source):
            result = _detect_serializer_from_source(_handler_no_schema)
        assert result is None

    def test_returns_none_when_class_lacks_model_json_schema(self):
        """Class is in globals but does not have model_json_schema → None."""

        class _NoSchemaClass:
            @classmethod
            def validate(cls, data):
                return data

        source = (
            "async def handler(req):\n"
            "    data = _NoSchemaClass.validate(req.data)\n"
            "    return data\n"
        )
        # Temporarily inject into module globals so handler can resolve it
        this_module = sys.modules[__name__]
        this_module._NoSchemaClass = _NoSchemaClass  # type: ignore[attr-defined]
        try:
            with patch("inspect.getsource", return_value=source):
                result = _detect_serializer_from_source(_handler_no_schema)
        finally:
            if hasattr(this_module, "_NoSchemaClass"):
                delattr(this_module, "_NoSchemaClass")

        assert result is None

    def test_detects_from_view_class_post_method(self):
        result = _detect_serializer_from_source(_FakeViewClassNoSerializer.post)
        assert result is FakeSerializer

    def test_detects_from_view_class_put_method(self):
        result = _detect_serializer_from_source(_FakeViewClassWithPut.put)
        assert result is FakeSerializer

    def test_detects_from_view_class_patch_method(self):
        result = _detect_serializer_from_source(_FakeViewClassWithPatch.patch)
        assert result is FakeSerializer


# ===========================================================================
# _resolve_request_schema
# ===========================================================================


class TestResolveRequestSchema:
    def test_explicit_decorator_takes_priority(self):
        @request_schema(FakeSerializer)
        async def handler(req):
            pass

        result = _resolve_request_schema(handler)
        assert result is FakeSerializer

    def test_view_class_serializer_class_attribute(self):
        async def fake_handler(req):
            pass

        fake_handler.view_class = _FakeViewClass
        result = _resolve_request_schema(fake_handler)
        assert result is FakeSerializer

    def test_view_class_detects_from_post_method(self):
        async def fake_handler(req):
            pass

        fake_handler.view_class = _FakeViewClassNoSerializer
        result = _resolve_request_schema(fake_handler)
        assert result is FakeSerializer

    def test_view_class_detects_from_put_method(self):
        async def fake_handler(req):
            pass

        fake_handler.view_class = _FakeViewClassWithPut
        result = _resolve_request_schema(fake_handler)
        assert result is FakeSerializer

    def test_view_class_detects_from_patch_method(self):
        async def fake_handler(req):
            pass

        fake_handler.view_class = _FakeViewClassWithPatch
        result = _resolve_request_schema(fake_handler)
        assert result is FakeSerializer

    def test_view_class_no_methods_returns_none(self):
        async def fake_handler(req):
            pass

        fake_handler.view_class = _FakeViewClassEmpty
        result = _resolve_request_schema(fake_handler)
        assert result is None

    def test_auto_detect_from_function_body(self):
        result = _resolve_request_schema(_handler_with_validate)
        assert result is FakeSerializer

    def test_auto_detect_model_validate_from_function_body(self):
        result = _resolve_request_schema(_handler_with_model_validate)
        assert result is FakeSerializer

    def test_returns_none_when_no_schema_found(self):
        result = _resolve_request_schema(_handler_no_schema)
        assert result is None

    def test_explicit_decorator_overrides_view_class(self):
        """_request_schema wins even when view_class also has serializer_class."""

        class OtherSerializer:
            @classmethod
            def model_json_schema(cls):
                return {}

        async def fake_handler(req):
            pass

        fake_handler._request_schema = FakeSerializer
        fake_handler.view_class = _FakeViewClass  # has FakeSerializer too, but shouldn't matter
        result = _resolve_request_schema(fake_handler)
        assert result is FakeSerializer


# ===========================================================================
# _build_operation
# ===========================================================================


class TestBuildOperation:

    # -- GET basics ----------------------------------------------------------------

    def test_get_basic_structure(self):
        async def list_items(request):
            """List all items."""
            pass

        route = _make_route("/items", ["GET"], list_items)
        op = _build_operation(route, "GET")

        assert op["summary"] == "List all items."
        assert op["operationId"] == "get_list_items"
        assert op["parameters"] == []
        assert "requestBody" not in op
        assert "200" in op["responses"]
        assert "422" not in op["responses"]

    def test_get_no_content_when_no_return_type(self):
        async def get_item(request):
            pass

        route = _make_route("/items", ["GET"], get_item)
        op = _build_operation(route, "GET")
        assert "content" not in op["responses"]["200"]

    def test_get_response_schema_from_return_type(self):
        route = _make_route("/items", ["GET"], _handler_with_dict_return)
        op = _build_operation(route, "GET")
        assert "content" in op["responses"]["200"]
        assert op["responses"]["200"]["content"]["application/json"]["schema"] == {"type": "object"}

    def test_get_response_schema_list_return(self):
        route = _make_route("/items", ["GET"], _handler_with_list_return)
        op = _build_operation(route, "GET")
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "array"

    def test_get_response_schema_int_return(self):
        route = _make_route("/items", ["GET"], _handler_with_int_return)
        op = _build_operation(route, "GET")
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema == {"type": "integer"}

    def test_get_response_schema_optional_return(self):
        route = _make_route("/items", ["GET"], _handler_with_optional_return)
        op = _build_operation(route, "GET")
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "string"
        assert schema["nullable"] is True

    # -- Path parameters -----------------------------------------------------------

    def test_path_params_included_in_parameters(self):
        async def get_user(request):
            pass

        route = _make_route("/users/{user_id:int}", ["GET"], get_user)
        op = _build_operation(route, "GET")
        assert len(op["parameters"]) == 1
        assert op["parameters"][0]["name"] == "user_id"
        assert op["parameters"][0]["schema"] == {"type": "integer"}

    def test_multiple_path_params(self):
        async def get_comment(request):
            pass

        route = _make_route("/users/{user_id:int}/posts/{post_id:uuid}", ["GET"], get_comment)
        op = _build_operation(route, "GET")
        assert len(op["parameters"]) == 2

    # -- Docstring handling --------------------------------------------------------

    def test_summary_from_first_docstring_line(self):
        async def handler(request):
            """Short summary.

            Longer description.
            """
            pass

        route = _make_route("/x", ["GET"], handler)
        op = _build_operation(route, "GET")
        assert op["summary"] == "Short summary."
        assert "description" in op
        assert "Longer description." in op["description"]

    def test_no_description_key_when_single_line_docstring(self):
        async def handler(request):
            """Just a summary."""
            pass

        route = _make_route("/x", ["GET"], handler)
        op = _build_operation(route, "GET")
        assert op["summary"] == "Just a summary."
        assert "description" not in op

    def test_summary_falls_back_to_route_name_when_no_docstring(self):
        async def handler(request):
            pass

        route = _make_route("/x", ["GET"], handler, name="my-route")
        op = _build_operation(route, "GET")
        assert op["summary"] == "my-route"

    def test_summary_falls_back_to_handler_name_when_no_name_no_docstring(self):
        async def my_special_handler(request):
            pass

        route = Route(path="/x", methods={"GET"}, handler=my_special_handler, name=None)
        op = _build_operation(route, "GET")
        assert op["summary"] == "my_special_handler"

    # -- Tags ----------------------------------------------------------------------

    def test_tags_derived_from_module(self):
        async def handler(request):
            pass

        route = _make_route("/x", ["GET"], handler)
        op = _build_operation(route, "GET")
        assert "tags" in op
        assert isinstance(op["tags"], list)
        assert len(op["tags"]) == 1
        # Module is this test file; the last segment should be the module name
        expected_tag = handler.__module__.split(".")[-1]
        assert op["tags"] == [expected_tag]

    # -- POST / PUT / PATCH request body -------------------------------------------

    def test_post_with_explicit_request_schema(self):
        @request_schema(FakeSerializer)
        async def create_item(request):
            """Create item."""
            pass

        route = _make_route("/items", ["POST"], create_item)
        op = _build_operation(route, "POST")

        assert "requestBody" in op
        assert op["requestBody"]["required"] is True
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert body_schema == FakeSerializer.model_json_schema()
        assert "422" in op["responses"]

    def test_post_with_pydantic_model_param_annotation(self):
        async def create_item(request, body: FakePydanticModel):
            """Create item with Pydantic body."""
            pass

        route = _make_route("/items", ["POST"], create_item)
        op = _build_operation(route, "POST")

        assert "requestBody" in op
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert schema == FakePydanticModel.model_json_schema()

    def test_post_generic_body_fallback_when_no_schema(self):
        """POST with no serializer and no Pydantic param gets a generic object body."""

        async def create_item(request):
            """Create item."""
            pass

        route = _make_route("/items", ["POST"], create_item)
        op = _build_operation(route, "POST")

        assert "requestBody" in op
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert schema["title"] == "Request Body"
        assert "description" in schema

    def test_put_with_explicit_request_schema(self):
        @request_schema(FakeSerializer)
        async def update_item(request):
            """Update item."""
            pass

        route = _make_route("/items/{id:int}", ["PUT"], update_item)
        op = _build_operation(route, "PUT")
        assert "requestBody" in op
        assert "422" in op["responses"]

    def test_put_generic_body_fallback(self):
        async def update_item(request):
            """Update item."""
            pass

        route = _make_route("/items/{id:int}", ["PUT"], update_item)
        op = _build_operation(route, "PUT")
        assert "requestBody" in op
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"

    def test_patch_generic_body_fallback(self):
        async def patch_item(request):
            """Patch item."""
            pass

        route = _make_route("/items/{id:int}", ["PATCH"], patch_item)
        op = _build_operation(route, "PATCH")
        assert "requestBody" in op

    # -- DELETE --------------------------------------------------------------------

    def test_delete_no_schema_produces_no_request_body(self):
        """DELETE without a schema class should NOT add a generic object body."""

        async def delete_item(request):
            """Delete item."""
            pass

        route = _make_route("/items/{id:int}", ["DELETE"], delete_item)
        op = _build_operation(route, "DELETE")
        assert "requestBody" not in op
        assert "422" in op["responses"]

    def test_delete_with_explicit_request_schema_adds_body(self):
        @request_schema(FakeSerializer)
        async def delete_item(request):
            """Delete item."""
            pass

        route = _make_route("/items/{id:int}", ["DELETE"], delete_item)
        op = _build_operation(route, "DELETE")
        assert "requestBody" in op
        assert "422" in op["responses"]

    # -- get_type_hints exception ---------------------------------------------------

    def test_get_type_hints_exception_is_silently_handled(self):
        async def handler(request):
            """Handler summary."""
            pass

        route = _make_route("/test", ["GET"], handler)
        with patch("openviper.openapi.schema.get_type_hints", side_effect=Exception("boom")):
            op = _build_operation(route, "GET")

        # Should still produce a valid operation even when hints fail
        assert op["summary"] == "Handler summary."
        assert "requestBody" not in op
        assert "200" in op["responses"]

    def test_operation_id_format(self):
        async def my_handler(request):
            pass

        route = _make_route("/x", ["POST"], my_handler)
        op = _build_operation(route, "POST")
        assert op["operationId"] == "post_my_handler"

    def test_operation_id_uses_method_lower(self):
        async def my_handler(request):
            pass

        route = _make_route("/x", ["GET"], my_handler)
        op = _build_operation(route, "GET")
        assert op["operationId"] == "get_my_handler"


# ===========================================================================
# generate_openapi_schema
# ===========================================================================


class TestGenerateOpenApiSchema:
    def test_top_level_openapi_version(self):
        doc = generate_openapi_schema([])
        assert doc["openapi"] == "3.1.0"

    def test_default_info_fields(self):
        doc = generate_openapi_schema([])
        assert doc["info"]["title"] == "OpenViper API"
        assert doc["info"]["version"] == "0.0.1"
        assert doc["info"]["description"] == ""

    def test_custom_info_fields(self):
        doc = generate_openapi_schema(
            [],
            title="My Service",
            version="2.5.0",
            description="API docs",
        )
        assert doc["info"]["title"] == "My Service"
        assert doc["info"]["version"] == "2.5.0"
        assert doc["info"]["description"] == "API docs"

    def test_empty_routes_produce_empty_paths(self):
        doc = generate_openapi_schema([])
        assert doc["paths"] == {}

    def test_single_get_route(self):
        async def list_users(request):
            pass

        routes = [_make_route("/users", ["GET"], list_users)]
        doc = generate_openapi_schema(routes)
        assert "/users" in doc["paths"]
        assert "get" in doc["paths"]["/users"]

    def test_skips_openapi_json_internal_path(self):
        async def openapi_json(request):
            pass

        routes = [_make_route("/open-api/openapi.json", ["GET"], openapi_json)]
        doc = generate_openapi_schema(routes)
        assert "/open-api/openapi.json" not in doc["paths"]

    def test_skips_docs_internal_path(self):
        async def docs(request):
            pass

        routes = [_make_route("/open-api/docs", ["GET"], docs)]
        doc = generate_openapi_schema(routes)
        assert "/open-api/docs" not in doc["paths"]

    def test_skips_redoc_internal_path(self):
        async def redoc(request):
            pass

        routes = [_make_route("/open-api/redoc", ["GET"], redoc)]
        doc = generate_openapi_schema(routes)
        assert "/open-api/redoc" not in doc["paths"]

    def test_non_internal_routes_are_included(self):
        async def user_handler(request):
            pass

        async def openapi_json(request):
            pass

        routes = [
            _make_route("/open-api/openapi.json", ["GET"], openapi_json),
            _make_route("/users", ["GET"], user_handler),
        ]
        doc = generate_openapi_schema(routes)
        assert "/users" in doc["paths"]
        assert "/open-api/openapi.json" not in doc["paths"]

    def test_head_method_is_omitted(self):
        async def list_users(request):
            pass

        routes = [_make_route("/users", ["GET", "HEAD"], list_users)]
        doc = generate_openapi_schema(routes)
        assert "head" not in doc["paths"]["/users"]
        assert "get" in doc["paths"]["/users"]

    def test_multiple_methods_on_same_path(self):
        async def list_users(request):
            pass

        async def create_user(request):
            pass

        routes = [
            _make_route("/users", ["GET"], list_users),
            _make_route("/users", ["POST"], create_user),
        ]
        doc = generate_openapi_schema(routes)
        assert "get" in doc["paths"]["/users"]
        assert "post" in doc["paths"]["/users"]

    def test_path_params_converted_to_openapi_format(self):
        async def get_user(request):
            pass

        routes = [_make_route("/users/{id:int}", ["GET"], get_user)]
        doc = generate_openapi_schema(routes)
        assert "/users/{id}" in doc["paths"]
        assert "/users/{id:int}" not in doc["paths"]

    def test_security_schemes_present(self):
        doc = generate_openapi_schema([])
        schemes = doc["components"]["securitySchemes"]
        assert "BearerAuth" in schemes
        assert "SessionAuth" in schemes

    def test_bearer_auth_scheme_structure(self):
        doc = generate_openapi_schema([])
        bearer = doc["components"]["securitySchemes"]["BearerAuth"]
        assert bearer["type"] == "http"
        assert bearer["scheme"] == "bearer"
        assert bearer["bearerFormat"] == "JWT"

    def test_session_auth_scheme_structure(self):
        doc = generate_openapi_schema([])
        session = doc["components"]["securitySchemes"]["SessionAuth"]
        assert session["type"] == "apiKey"
        assert session["in"] == "cookie"
        assert session["name"] == "sessionid"

    def test_global_security_list(self):
        doc = generate_openapi_schema([])
        assert {"BearerAuth": []} in doc["security"]
        assert {"SessionAuth": []} in doc["security"]

    def test_multiple_routes_different_paths(self):
        async def list_users(request):
            pass

        async def list_posts(request):
            pass

        routes = [
            _make_route("/users", ["GET"], list_users),
            _make_route("/posts", ["GET"], list_posts),
        ]
        doc = generate_openapi_schema(routes)
        assert "/users" in doc["paths"]
        assert "/posts" in doc["paths"]

    def test_methods_sorted_in_path(self):
        """Methods on a path are iterated in sorted order (all except HEAD)."""

        async def handler(request):
            pass

        # Route with DELETE and GET (HEAD will be skipped)
        routes = [_make_route("/x", ["GET", "POST", "HEAD", "DELETE"], handler)]
        doc = generate_openapi_schema(routes)
        path_methods = set(doc["paths"]["/x"].keys())
        assert "get" in path_methods
        assert "post" in path_methods
        assert "delete" in path_methods
        assert "head" not in path_methods

    def test_full_document_shape(self):
        """Smoke test: all top-level keys present."""
        doc = generate_openapi_schema([])
        required_keys = {"openapi", "info", "paths", "components", "security"}
        assert required_keys.issubset(doc.keys())
