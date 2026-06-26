"""Unit tests for TokenAuth integration in OpenAPI schema generation."""

from __future__ import annotations

from openviper.http.views import View
from openviper.openapi.schema import (
    build_operation,
    build_per_route_security,
    generate_openapi_schema,
    reset_openapi_cache,
)


class FakeRoute:
    def __init__(
        self,
        path: str,
        methods: list[str],
        handler: object,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.path = path
        self.methods = methods
        self.handler = handler
        self.name = name or getattr(handler, "__name__", "handler")
        self.tags = tags or []


# Use type() so that cls.__name__ returns the intended string
# (a class-body ``__name__ = ...`` is shadowed by the metaclass descriptor).
FakeTokenAuth = type("TokenAuthentication", (), {})
FakeJWTAuth = type("JWTAuthentication", (), {})
FakeSessionAuth = type("SessionAuthentication", (), {})
FakeUnknownAuth = type("CustomAuthentication", (), {})


class TestTokenAuthSecurityScheme:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_token_auth_in_security_schemes(self) -> None:
        schema = generate_openapi_schema([])
        schemes = schema["components"]["securitySchemes"]
        assert "TokenAuth" in schemes

    def test_token_auth_scheme_type_is_api_key(self) -> None:
        schema = generate_openapi_schema([])
        token_scheme = schema["components"]["securitySchemes"]["TokenAuth"]
        assert token_scheme["type"] == "apiKey"
        assert token_scheme["in"] == "header"
        assert token_scheme["name"] == "Authorization"

    def test_token_auth_in_global_security(self) -> None:
        schema = generate_openapi_schema([])
        security_names = [list(s.keys())[0] for s in schema["security"]]
        assert "TokenAuth" in security_names

    def test_global_security_includes_all_three_schemes(self) -> None:
        schema = generate_openapi_schema([])
        security_names = {list(s.keys())[0] for s in schema["security"]}
        assert security_names == {"BearerAuth", "SessionAuth", "TokenAuth"}


class TestBuildPerRouteSecurity:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_returns_none_when_no_auth_classes(self) -> None:
        async def handler(request):
            pass

        result = build_per_route_security(handler)
        assert result is None

    def test_returns_none_when_auth_classes_empty_list(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = []
        result = build_per_route_security(handler)
        assert result is None

    def test_returns_token_auth_scheme_for_token_auth(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = [FakeTokenAuth]
        result = build_per_route_security(handler)
        assert result == [{"TokenAuth": []}]

    def test_returns_bearer_auth_for_jwt_auth(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = [FakeJWTAuth]
        result = build_per_route_security(handler)
        assert result == [{"BearerAuth": []}]

    def test_returns_session_auth_for_session_auth(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = [FakeSessionAuth]
        result = build_per_route_security(handler)
        assert result == [{"SessionAuth": []}]

    def test_multiple_auth_classes_returned_in_order(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = [FakeTokenAuth, FakeJWTAuth]
        result = build_per_route_security(handler)
        assert result == [{"TokenAuth": []}, {"BearerAuth": []}]

    def test_unknown_auth_class_excluded(self) -> None:
        async def handler(request):
            pass

        handler.authentication_classes = [FakeUnknownAuth]
        result = build_per_route_security(handler)
        assert result is None

    def test_reads_from_view_class_authentication_classes(self) -> None:
        class MyView:
            authentication_classes = [FakeTokenAuth]

        async def handler(request):
            pass

        handler.view_class = MyView
        result = build_per_route_security(handler)
        assert result == [{"TokenAuth": []}]

    def test_view_class_empty_auth_classes_returns_none(self) -> None:
        class MyView:
            authentication_classes: list = []

        async def handler(request):
            pass

        handler.view_class = MyView
        result = build_per_route_security(handler)
        assert result is None


class TestBuildOperationWithTokenAuth:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_operation_includes_per_route_security_for_token_auth(self) -> None:
        async def secure_endpoint(request):
            """Secured endpoint."""

        secure_endpoint.authentication_classes = [FakeTokenAuth]
        route = FakeRoute("/secure/", ["GET"], secure_endpoint)
        op = build_operation(route, "GET")
        assert "security" in op
        assert {"TokenAuth": []} in op["security"]

    def test_operation_without_auth_classes_has_no_security_key(self) -> None:
        async def open_endpoint(request):
            """Open endpoint."""

        route = FakeRoute("/open/", ["GET"], open_endpoint)
        op = build_operation(route, "GET")
        assert "security" not in op

    def test_schema_path_has_per_route_security_for_token_auth_view(self) -> None:
        reset_openapi_cache()

        async def token_only(request):
            """Token-only view."""

        token_only.authentication_classes = [FakeTokenAuth]
        route = FakeRoute("/token-only/", ["GET"], token_only)
        schema = generate_openapi_schema([route], title="T")
        ops = schema["paths"]["/token-only/"]
        assert "security" in ops["get"]
        assert {"TokenAuth": []} in ops["get"]["security"]

    def test_schema_omits_options_operations(self) -> None:
        reset_openapi_cache()

        async def endpoint(request):
            """Endpoint with runtime OPTIONS support."""

        route = FakeRoute("/scores/", ["GET", "OPTIONS"], endpoint)
        schema = generate_openapi_schema([route], title="T")
        ops = schema["paths"]["/scores/"]
        assert "get" in ops
        assert "options" not in ops

    def test_class_view_operation_uses_method_docstring(self) -> None:
        class PostView(View):
            async def post(self, request):
                """Create a post.

                Visible method-level documentation.
                """

        handler = PostView.as_view()
        route = FakeRoute("/posts/", ["POST"], handler)

        op = build_operation(route, "POST")

        assert op["summary"] == "Create a post."
        assert op["description"] == "<p>Visible method-level documentation.</p>"

    def test_inline_body_docstring_builds_request_schema(self) -> None:
        class PostView(View):
            async def post(self, request):
                """Create a post.

                Body: {
                    "title": str,
                    "views": int,
                    "state": str,  # "DRAFT", "PUBLISHED"
                    "author_id": str (UUID)
                }
                """

        handler = PostView.as_view()
        route = FakeRoute("/posts/", ["POST"], handler)

        op = build_operation(route, "POST")
        schema = op["requestBody"]["content"]["application/json"]["schema"]

        assert schema == {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "views": {"type": "integer"},
                "state": {"type": "string", "enum": ["DRAFT", "PUBLISHED"]},
                "author_id": {"type": "string", "format": "uuid"},
            },
            "required": ["title", "views", "state", "author_id"],
            "title": "Request Body",
        }

    def test_multiline_docstring_description_renders_structured_html(self) -> None:
        class PostView(View):
            async def post(self, request):
                """Create a post.

                Request: CreatePostSerializer

                Example Request: {
                    "title": "Hello"
                }

                Example Response: {
                    "message": "created"
                }
                """

        handler = PostView.as_view()
        route = FakeRoute("/posts/", ["POST"], handler)

        op = build_operation(route, "POST")

        assert op["description"] == (
            "<p><strong>Request:</strong> CreatePostSerializer</p>"
            "<p><strong>Example Request:</strong></p>"
            "<pre><code>{\n&quot;title&quot;: &quot;Hello&quot;\n}</code></pre>"
            "<p><strong>Example Response:</strong></p>"
            "<pre><code>{\n&quot;message&quot;: &quot;created&quot;\n}</code></pre>"
        )
