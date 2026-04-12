"""Unit tests for TokenAuth integration in OpenAPI schema generation."""

from __future__ import annotations

from openviper.openapi.schema import (
    _build_operation,
    _build_per_route_security,
    generate_openapi_schema,
    reset_openapi_cache,
)


class _FakeRoute:
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
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        result = _build_per_route_security(handler)
        assert result is None

    def test_returns_none_when_auth_classes_empty_list(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = []  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result is None

    def test_returns_token_auth_scheme_for_token_auth(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = [FakeTokenAuth]  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result == [{"TokenAuth": []}]

    def test_returns_bearer_auth_for_jwt_auth(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = [FakeJWTAuth]  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result == [{"BearerAuth": []}]

    def test_returns_session_auth_for_session_auth(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = [FakeSessionAuth]  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result == [{"SessionAuth": []}]

    def test_multiple_auth_classes_returned_in_order(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = [FakeTokenAuth, FakeJWTAuth]  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result == [{"TokenAuth": []}, {"BearerAuth": []}]

    def test_unknown_auth_class_excluded(self) -> None:
        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.authentication_classes = [FakeUnknownAuth]  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result is None

    def test_reads_from_view_class_authentication_classes(self) -> None:
        class MyView:
            authentication_classes = [FakeTokenAuth]

        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.view_class = MyView  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result == [{"TokenAuth": []}]

    def test_view_class_empty_auth_classes_returns_none(self) -> None:
        class MyView:
            authentication_classes: list = []

        async def handler(request):  # type: ignore[no-untyped-def]
            pass

        handler.view_class = MyView  # type: ignore[attr-defined]
        result = _build_per_route_security(handler)
        assert result is None


class TestBuildOperationWithTokenAuth:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_operation_includes_per_route_security_for_token_auth(self) -> None:
        async def secure_endpoint(request):  # type: ignore[no-untyped-def]
            """Secured endpoint."""

        secure_endpoint.authentication_classes = [FakeTokenAuth]  # type: ignore[attr-defined]
        route = _FakeRoute("/secure/", ["GET"], secure_endpoint)
        op = _build_operation(route, "GET")
        assert "security" in op
        assert {"TokenAuth": []} in op["security"]

    def test_operation_without_auth_classes_has_no_security_key(self) -> None:
        async def open_endpoint(request):  # type: ignore[no-untyped-def]
            """Open endpoint."""

        route = _FakeRoute("/open/", ["GET"], open_endpoint)
        op = _build_operation(route, "GET")
        assert "security" not in op

    def test_schema_path_has_per_route_security_for_token_auth_view(self) -> None:
        reset_openapi_cache()

        async def token_only(request):  # type: ignore[no-untyped-def]
            """Token-only view."""

        token_only.authentication_classes = [FakeTokenAuth]  # type: ignore[attr-defined]
        route = _FakeRoute("/token-only/", ["GET"], token_only)
        schema = generate_openapi_schema([route], title="T")
        ops = schema["paths"]["/token-only/"]
        assert "security" in ops["get"]
        assert {"TokenAuth": []} in ops["get"]["security"]
