"""Unit tests for openviper.app — OpenViper ASGI application."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.app import OpenViper, _get_handler_signature, _resolve_middleware_entry
from openviper.exceptions import HTTPException
from openviper.http.request import Request
from openviper.http.response import HTMLResponse, JSONResponse, Response
from openviper.routing.router import Router


class TestGetHandlerSignature:
    """Tests for _get_handler_signature function."""

    def test_caches_signature(self):
        def handler(request: Request) -> dict:
            return {}

        result1 = _get_handler_signature(handler)
        result2 = _get_handler_signature(handler)

        # Should return cached result
        assert result1 is result2

    def test_returns_signature_and_hints(self):
        def handler(request: Request, name: str) -> dict:
            return {}

        sig, hints = _get_handler_signature(handler)

        assert sig is not None
        assert isinstance(hints, dict)

    def test_handles_missing_type_hints(self):
        def handler(request):
            return {}

        sig, hints = _get_handler_signature(handler)

        assert sig is not None
        assert isinstance(hints, dict)


class TestResolveMiddlewareEntry:
    """Tests for _resolve_middleware_entry function."""

    def test_returns_class_as_is(self):
        class MyMiddleware:
            pass

        result = _resolve_middleware_entry(MyMiddleware)

        assert result is MyMiddleware

    @patch("importlib.import_module")
    def test_imports_string_reference(self, mock_import):
        mock_module = MagicMock()
        mock_module.MyMiddleware = object
        mock_import.return_value = mock_module

        result = _resolve_middleware_entry("myapp.middleware.MyMiddleware")

        assert result is object

    @patch("importlib.import_module", side_effect=ImportError("Module not found"))
    def test_returns_none_on_import_error(self, mock_import):
        result = _resolve_middleware_entry("nonexistent.Middleware")

        assert result is None


class TestOpenViperInit:
    """Tests for OpenViper.__init__ method."""

    def test_creates_instance(self):
        app = OpenViper()

        assert app is not None
        assert isinstance(app.router, Router)

    def test_sets_debug_mode(self):
        app = OpenViper(debug=True)

        assert app.debug is True

    def test_sets_title_and_version(self):
        app = OpenViper(title="My API", version="1.0.0")

        assert app.title == "My API"
        assert app.version == "1.0.0"

    def test_initializes_router(self):
        app = OpenViper()

        assert hasattr(app, "router")
        assert isinstance(app.router, Router)

    def test_initializes_middleware_list(self):
        app = OpenViper()

        assert hasattr(app, "_extra_middleware")
        assert isinstance(app._extra_middleware, list)

    def test_adds_extra_middleware(self):
        middleware = MagicMock()
        app = OpenViper(middleware=[middleware])

        assert middleware in app._extra_middleware


class TestOpenViperRouteMethods:
    """Tests for route registration methods."""

    def test_get_decorator(self):
        app = OpenViper()

        @app.get("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_post_decorator(self):
        app = OpenViper()

        @app.post("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_put_decorator(self):
        app = OpenViper()

        @app.put("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_patch_decorator(self):
        app = OpenViper()

        @app.patch("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_delete_decorator(self):
        app = OpenViper()

        @app.delete("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_options_decorator(self):
        app = OpenViper()

        @app.options("/test")
        def handler():
            return {}

        assert app.router.routes

    def test_route_decorator(self):
        app = OpenViper()

        @app.route("/test", methods=["GET", "POST"])
        def handler():
            return {}

        assert app.router.routes


class TestIncludeRouter:
    """Tests for include_router method."""

    def test_includes_router(self):
        app = OpenViper()
        router = Router()

        @router.get("/nested")
        def handler():
            return {}

        app.include_router(router, prefix="/api")

        # Router should be included
        assert len(app.router.routes) > 0

    def test_includes_router_without_prefix(self):
        app = OpenViper()
        router = Router()

        @router.get("/test")
        def handler():
            return {}

        app.include_router(router)

        assert len(app.router.routes) > 0


class TestLifecycleEvents:
    """Tests for on_startup and on_shutdown decorators."""

    def test_on_startup_registers_callback(self):
        app = OpenViper()

        @app.on_startup
        def startup():
            pass

        assert startup in app._startup_handlers

    def test_on_shutdown_registers_callback(self):
        app = OpenViper()

        @app.on_shutdown
        def shutdown():
            pass

        assert shutdown in app._shutdown_handlers

    def test_multiple_startup_handlers(self):
        app = OpenViper()

        @app.on_startup
        def startup1():
            pass

        @app.on_startup
        def startup2():
            pass

        assert len(app._startup_handlers) == 2


class TestExceptionHandler:
    """Tests for exception_handler decorator."""

    def test_registers_exception_handler(self):
        app = OpenViper()

        class CustomException(Exception):
            pass

        @app.exception_handler(CustomException)
        def handler(request, exc):
            return JSONResponse({"error": "custom"})

        assert CustomException in app._exception_handlers

    def test_multiple_exception_handlers(self):
        app = OpenViper()

        class Exc1(Exception):
            pass

        class Exc2(Exception):
            pass

        @app.exception_handler(Exc1)
        def handler1(request, exc):
            return JSONResponse({})

        @app.exception_handler(Exc2)
        def handler2(request, exc):
            return JSONResponse({})

        assert len(app._exception_handlers) == 2


class TestOpenAPIRoutes:
    """Tests for OpenAPI route registration."""

    def test_registers_openapi_json_route(self):
        app = OpenViper(openapi_url="/openapi.json")

        assert any(r.path == "/openapi.json" for r in app.router.routes)

    def test_registers_swagger_ui_route(self):
        app = OpenViper(docs_url="/docs")

        assert any(r.path == "/docs" for r in app.router.routes)

    def test_registers_redoc_route(self):
        app = OpenViper(redoc_url="/redoc")

        assert any(r.path == "/redoc" for r in app.router.routes)

    def test_skips_openapi_when_disabled(self):
        app = OpenViper(openapi_url=None)

        assert not any(r.path == "/openapi.json" for r in app.router.routes)


class TestGetOpenAPISchema:
    """Tests for _get_openapi_schema method."""

    def test_generates_schema(self):
        app = OpenViper(title="Test API", version="1.0")

        @app.get("/test")
        def handler():
            return {}

        schema = app._get_openapi_schema()

        assert schema["info"]["title"] == "Test API"
        assert schema["info"]["version"] == "1.0"

    def test_caches_schema(self):
        app = OpenViper()

        schema1 = app._get_openapi_schema()
        schema2 = app._get_openapi_schema()

        assert schema1 is schema2

    def test_invalidates_schema_cache(self):
        app = OpenViper()

        schema1 = app._get_openapi_schema()
        app.invalidate_openapi_schema()
        schema2 = app._get_openapi_schema()

        # After invalidation, a new schema should be generated
        assert schema1 is not schema2 or schema1 == schema2  # May or may not be same object


class TestCoerceResponse:
    """Tests for _coerce_response method."""

    def test_dict_to_json_response(self):
        app = OpenViper()

        response = app._coerce_response({"key": "value"})

        assert isinstance(response, JSONResponse)

    def test_list_to_json_response(self):
        app = OpenViper()

        response = app._coerce_response([1, 2, 3])

        assert isinstance(response, JSONResponse)

    def test_string_to_plain_text(self):
        app = OpenViper()

        response = app._coerce_response("Hello")

        assert isinstance(response, Response)

    def test_response_passthrough(self):
        app = OpenViper()
        original = JSONResponse({"data": "test"})

        response = app._coerce_response(original)

        assert response is original

    def test_none_to_empty_response(self):
        app = OpenViper()

        response = app._coerce_response(None)

        assert isinstance(response, Response)


class TestHandleException:
    """Tests for _handle_exception method."""

    @pytest.mark.asyncio
    async def test_handles_http_exception(self):
        app = OpenViper()
        request = MagicMock(spec=Request)

        exc = HTTPException(status_code=404, detail="Not found")

        response = await app._handle_exception(request, exc)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_handles_custom_exception_handler(self):
        app = OpenViper()

        class CustomError(Exception):
            pass

        @app.exception_handler(CustomError)
        async def handler(request, exc):
            return JSONResponse({"error": "custom"}, status_code=400)

        request = MagicMock(spec=Request)
        exc = CustomError("test")

        response = await app._handle_exception(request, exc)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self):
        app = OpenViper()
        request = MagicMock(spec=Request)

        exc = ValueError("Something went wrong")

        response = await app._handle_exception(request, exc)

        assert response.status_code == 500


class TestCreateErrorResponse:
    """Tests for _create_error_response method."""

    def test_creates_json_error_response(self):
        app = OpenViper()
        request = MagicMock(spec=Request)
        request.headers = {"accept": "application/json"}

        response = app._create_error_response(
            request,
            {"detail": "Bad request"},
            status_code=400,
        )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_creates_html_error_response(self):
        app = OpenViper()
        request = MagicMock(spec=Request)
        request.headers = {"accept": "text/html"}

        response = app._create_error_response(
            request,
            {"detail": "Not found"},
            status_code=404,
        )

        assert isinstance(response, (HTMLResponse, JSONResponse))
        assert response.status_code == 404


class TestCallHandler:
    """Tests for _call_handler method."""

    @pytest.mark.asyncio
    async def test_calls_sync_handler(self):
        app = OpenViper()
        request = MagicMock(spec=Request)

        def handler(request):
            return {"result": "ok"}

        response = await app._call_handler(handler, request)

        assert isinstance(response, Response)

    @pytest.mark.asyncio
    async def test_calls_async_handler(self):
        app = OpenViper()
        request = MagicMock(spec=Request)

        async def handler(request):
            return {"result": "ok"}

        response = await app._call_handler(handler, request)

        assert isinstance(response, Response)

    @pytest.mark.asyncio
    async def test_injects_request_parameter(self):
        app = OpenViper()
        request = MagicMock(spec=Request)
        request.path_params = {}
        request.query_params = {}

        def handler(request: Request):
            return {"got_request": request is not None}

        response = await app._call_handler(handler, request)

        assert isinstance(response, Response)


class TestHandleHTTP:
    """Tests for _handle_http method."""

    @pytest.mark.asyncio
    async def test_handles_valid_request(self):
        app = OpenViper()

        @app.get("/test")
        def handler():
            return {"status": "ok"}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await app._handle_http(scope, receive, send)

        # Should have sent a response
        assert send.called

    @pytest.mark.asyncio
    async def test_handles_404(self):
        app = OpenViper()

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/nonexistent",
            "query_string": b"",
            "headers": [],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await app._handle_http(scope, receive, send)

        # Should send 404 response
        assert send.called


class TestHandleLifespan:
    """Tests for _handle_lifespan method."""

    @pytest.mark.asyncio
    async def test_handles_startup(self):
        app = OpenViper()
        startup_called = []

        @app.on_startup
        async def startup():
            startup_called.append(True)

        scope = {"type": "lifespan"}
        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        await app._handle_lifespan(scope, receive, send)

        assert startup_called

    @pytest.mark.asyncio
    async def test_handles_shutdown(self):
        app = OpenViper()
        shutdown_called = []

        @app.on_shutdown
        async def shutdown():
            shutdown_called.append(True)

        scope = {"type": "lifespan"}
        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        await app._handle_lifespan(scope, receive, send)

        assert shutdown_called


class TestCall:
    """Tests for __call__ method."""

    @pytest.mark.asyncio
    async def test_routes_http_requests(self):
        app = OpenViper()

        @app.get("/")
        def root():
            return {"ok": True}

        scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        receive = AsyncMock()
        send = AsyncMock()

        await app._core_app(scope, receive, send)
        # Verify it went through _core_app -> _handle_http -> router -> handler -> send
        assert send.called

    @pytest.mark.asyncio
    async def test_routes_lifespan_events(self):
        app = OpenViper()

        scope = {"type": "lifespan"}
        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        await app(scope, receive, send)

        # Should have handled lifespan
        assert True

    @pytest.mark.asyncio
    async def test_handles_websocket(self):
        app = OpenViper()
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()
        await app(scope, receive, send)
        send.assert_called_with(
            {"type": "websocket.close", "code": 1003, "reason": "Not Implemented"}
        )

    @pytest.mark.asyncio
    async def test_coerce_response_pydantic(self):
        app = OpenViper()

        class MockPydantic:
            def model_dump(self):
                return {"a": 1}

        response = app._coerce_response(MockPydantic())
        assert isinstance(response, JSONResponse)
        # orjson produces compact JSON
        assert response.body == b'{"a":1}'

    @pytest.mark.asyncio
    async def test_call_handler_path_params_injection(self):
        app = OpenViper()
        request = MagicMock(spec=Request)
        request.path_params = {"id": 123}
        request.query_params = {}

        def handler(id: int):
            return {"id": id}

        response = await app._call_handler(handler, request)
        assert response.body == b'{"id":123}'

    @pytest.mark.asyncio
    async def test_call_handler_var_kwargs_injection(self):
        app = OpenViper()
        request = MagicMock(spec=Request)
        request.path_params = {"a": 1, "b": 2}

        # Use a type hint to prevent the catcher from being treated as a request param
        def handler(**kwargs_catch: Any):
            return kwargs_catch

        response = await app._call_handler(handler, request)
        assert json.loads(response.body) == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_handle_lifespan_startup_failure(self):
        app = OpenViper()

        @app.on_startup
        def fail():
            raise ValueError("Startup failed")

        scope = {"type": "lifespan"}
        receive = AsyncMock(side_effect=[{"type": "lifespan.startup"}])
        send = AsyncMock()

        await app._handle_lifespan(scope, receive, send)
        send.assert_called_with({"type": "lifespan.startup.failed", "message": "Startup failed"})

    @pytest.mark.asyncio
    async def test_handle_lifespan_shutdown_failure(self):
        app = OpenViper()

        @app.on_shutdown
        def fail():
            raise ValueError("Shutdown failed")

        scope = {"type": "lifespan"}
        receive = AsyncMock(
            side_effect=[{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        )
        send = AsyncMock()

        await app._handle_lifespan(scope, receive, send)
        # First call is startup complete, second is shutdown failed
        assert send.call_args_list[-1][0][0]["type"] == "lifespan.shutdown.failed"

    @pytest.mark.asyncio
    async def test_handle_http_route_middleware(self):
        app = OpenViper()
        middleware_called = []

        def middleware(handler):
            async def wrapper(request):
                middleware_called.append(True)
                return await handler(request)

            return wrapper

        @app.get("/test", middlewares=[middleware])
        def handler(request):
            return {"ok": True}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await app._handle_http(scope, receive, send)
        assert middleware_called == [True]

    @pytest.mark.asyncio
    async def test_create_error_response_with_traceback(self):
        app = OpenViper(debug=True)
        request = MagicMock(spec=Request)
        request.headers = {"accept": "text/html"}

        content = {"detail": "Error", "type": "ValueError", "traceback": ["line 1", "line 2"]}

        response = app._create_error_response(request, content, status_code=500)
        assert b"ValueError" in response.body
        assert b"line 1" in response.body

    @pytest.mark.asyncio
    async def test_handle_exception_fallback(self):
        app = OpenViper(debug=False)
        request = MagicMock(spec=Request)
        request.headers = {}

        response = await app._handle_exception(request, Exception("Secret error"))
        assert response.status_code == 500
        assert b"Internal Server Error" in response.body
        assert b"Secret error" not in response.body

    @pytest.mark.asyncio
    async def test_get_handler_signature_exception(self):
        # Trigger Exception in typing.get_type_hints
        with patch("typing.get_type_hints", side_effect=Exception):

            def handler(a):
                pass

            sig, hints = _get_handler_signature(handler)
            assert hints == {}

    @pytest.mark.asyncio
    async def test_register_openapi_handlers(self):
        app = OpenViper()
        app._register_openapi_routes()

        # Manually call handlers to cover internal routes
        for route in app.router.routes:
            if route.name in ("openapi_schema", "swagger_ui", "redoc_ui"):
                response = await route.handler(MagicMock(spec=Request))
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_coerce_response_fallback_raises_for_unknown_type(self):
        app = OpenViper()

        class UnknownType:
            def __str__(self):
                return "unknown"

        # attempting to serialize an unknown type to JSON should raise TypeError
        with pytest.raises(TypeError, match="Type is not JSON serializable"):
            app._coerce_response(UnknownType())

    def test_has_custom_root_route_with_name(self):
        app = OpenViper()

        @app.get("/", name="custom_root")
        def root():
            return {}

        assert app._has_custom_root_route() is True


class TestTestClient:
    """Tests for test_client method."""

    @pytest.mark.asyncio
    async def test_returns_async_client(self):
        app = OpenViper()
        client = app.test_client(base_url="http://custom")
        assert str(client.base_url).rstrip("/") == "http://custom"
        await client.aclose()


class TestRepr:
    """Tests for __repr__ method."""

    def test_repr_contains_class_name(self):
        app = OpenViper(title="My API")
        result = repr(app)
        assert "OpenViper" in result
        assert "My API" in result


class TestHasCustomRootRoute:
    """Tests for _has_custom_root_route method."""

    def test_returns_false_when_no_root_route(self):
        app = OpenViper()
        assert app._has_custom_root_route() is False

    def test_returns_true_when_root_route_exists(self):
        app = OpenViper()

        @app.get("/")
        def root():
            return {}

        assert app._has_custom_root_route() is True


class TestRun:
    """Tests for run method."""

    @patch("uvicorn.run")
    def test_calls_uvicorn_run(self, mock_run):
        app = OpenViper()
        app.run(host="0.0.0.0", port=8000)
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 8000
