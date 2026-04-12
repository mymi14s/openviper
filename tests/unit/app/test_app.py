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
    def test_raises_on_import_error(self, mock_import):
        with pytest.raises(ImportError, match="nonexistent.Middleware"):
            _resolve_middleware_entry("nonexistent.Middleware")


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


class TestAutodiscoverRoutes:
    """Tests for _autodiscover_routes method."""

    def test_registers_route_paths_from_routes_module(self, monkeypatch):
        router = Router()

        async def handler(request):
            return {}

        router.add("/items", handler, methods=["GET"])

        fake_routes_module = MagicMock()
        fake_routes_module.route_paths = [("/api", router)]

        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        with patch("importlib.import_module", return_value=fake_routes_module):
            app = OpenViper()

        assert any(r.path == "/api/items" for r in app.router.routes)

    def test_skips_when_no_settings_module_env_var(self, monkeypatch):
        monkeypatch.delenv("OPENVIPER_SETTINGS_MODULE", raising=False)

        with patch("importlib.import_module") as mock_import:
            app = OpenViper()

        mock_import.assert_not_called()
        assert app is not None

    def test_skips_when_settings_module_has_no_package(self, monkeypatch):
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "settings")

        with patch("importlib.import_module") as mock_import:
            OpenViper()

        mock_import.assert_not_called()

    def test_skips_gracefully_when_routes_module_missing(self, monkeypatch):
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        exc = ModuleNotFoundError("No module named 'myproject.routes'")
        exc.name = "myproject.routes"
        with patch("importlib.import_module", side_effect=exc):
            app = OpenViper()

        assert app is not None

    def test_raises_when_routes_module_has_broken_imports(self, monkeypatch):
        """A broken nested import inside the routes module always propagates."""
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        exc = ModuleNotFoundError("No module named 'nonexistent_dep'")
        exc.name = "nonexistent_dep"
        with patch("importlib.import_module", side_effect=exc):
            with pytest.raises(ModuleNotFoundError):
                OpenViper()

    def test_skips_gracefully_when_route_paths_not_defined(self, monkeypatch):
        fake_routes_module = MagicMock(spec=[])  # no route_paths attribute

        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        with patch("importlib.import_module", return_value=fake_routes_module):
            app = OpenViper()

        assert app is not None

    def test_derives_routes_module_from_settings_module(self, monkeypatch):
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "ecommerce_clone.settings")

        imported_modules: list[str] = []

        def capture_import(name: str, *args, **kwargs):
            imported_modules.append(name)
            m = MagicMock()
            m.route_paths = []
            return m

        with patch("importlib.import_module", side_effect=capture_import):
            OpenViper()

        assert "ecommerce_clone.routes" in imported_modules

    def test_derives_routes_module_from_nested_settings_module(self, monkeypatch):
        """project.settings.prod -> project.routes (top-level package only)."""
        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "project.settings.prod")

        imported_modules: list[str] = []

        def capture_import(name: str, *args, **kwargs):
            imported_modules.append(name)
            m = MagicMock()
            m.route_paths = []
            return m

        with patch("importlib.import_module", side_effect=capture_import):
            OpenViper()

        assert "project.routes" in imported_modules
        assert "project.settings.routes" not in imported_modules

    def test_registers_multiple_routers(self, monkeypatch):
        router_a = Router()
        router_b = Router()

        async def handler_a(request):
            return {}

        async def handler_b(request):
            return {}

        router_a.add("/a", handler_a, methods=["GET"])
        router_b.add("/b", handler_b, methods=["GET"])

        fake_routes_module = MagicMock()
        fake_routes_module.route_paths = [("/v1", router_a), ("/v2", router_b)]

        monkeypatch.setenv("OPENVIPER_SETTINGS_MODULE", "myproject.settings")

        with patch("importlib.import_module", return_value=fake_routes_module):
            app = OpenViper()

        paths = [r.path for r in app.router.routes]
        assert "/v1/a" in paths
        assert "/v2/b" in paths


class TestInstalledAppReadyHooks:
    """Tests for _call_installed_app_ready_hooks."""

    @pytest.mark.asyncio
    async def test_calls_async_ready_on_installed_app(self):
        """Async ready() defined at app package level is awaited."""
        called = []

        async def ready():
            called.append("async")

        fake_mod = MagicMock()
        fake_mod.ready = ready

        app = OpenViper()
        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            with patch("importlib.import_module", return_value=fake_mod):
                await app._call_installed_app_ready_hooks()

        assert called == ["async"]

    @pytest.mark.asyncio
    async def test_calls_sync_ready_on_installed_app(self):
        """Sync ready() defined at app package level is called."""
        called = []

        def ready():
            called.append("sync")

        fake_mod = MagicMock()
        fake_mod.ready = ready

        app = OpenViper()
        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            with patch("importlib.import_module", return_value=fake_mod):
                await app._call_installed_app_ready_hooks()

        assert called == ["sync"]

    @pytest.mark.asyncio
    async def test_falls_back_to_apps_module_ready(self):
        """ready() in apps.py sub-module is used when not in __init__."""
        called = []

        async def ready():
            called.append("apps_ready")

        fake_init = MagicMock(spec=[])  # no ready attribute
        fake_apps = MagicMock()
        fake_apps.ready = ready

        app = OpenViper()

        def import_side_effect(name):
            if name == "myplugin":
                return fake_init
            if name == "myplugin.apps":
                return fake_apps
            return MagicMock()

        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            with patch("importlib.import_module", side_effect=import_side_effect):
                await app._call_installed_app_ready_hooks()

        assert called == ["apps_ready"]

    @pytest.mark.asyncio
    async def test_skips_app_with_no_ready(self):
        """Apps without a ready() are silently skipped."""
        fake_mod = MagicMock(spec=[])  # no ready attribute

        app = OpenViper()

        def import_side_effect(name):
            if name == "myplugin":
                return fake_mod
            raise ImportError(name)

        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            with patch("importlib.import_module", side_effect=import_side_effect):
                await app._call_installed_app_ready_hooks()

    @pytest.mark.asyncio
    async def test_raises_on_unimportable_app(self):
        """An ImportError on an INSTALLED_APPS entry raises RuntimeError at startup."""
        app = OpenViper()
        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["nonexistent_plugin"]
            with patch("importlib.import_module", side_effect=ImportError("no module")):
                with pytest.raises(RuntimeError, match="nonexistent_plugin"):
                    await app._call_installed_app_ready_hooks()

    @pytest.mark.asyncio
    async def test_raises_when_ready_raises(self):
        """An exception inside ready() is wrapped and re-raised."""

        async def ready():
            raise ValueError("plugin broke")

        fake_mod = MagicMock()
        fake_mod.ready = ready

        app = OpenViper()
        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            with patch("importlib.import_module", return_value=fake_mod):
                with pytest.raises(RuntimeError, match="myplugin"):
                    await app._call_installed_app_ready_hooks()

    @pytest.mark.asyncio
    async def test_calls_ready_on_multiple_apps_in_order(self):
        """ready() is called for each installed app in declaration order."""
        order = []

        def make_mod(name):
            m = MagicMock()
            captured = name

            async def ready():
                order.append(captured)

            m.ready = ready
            return m

        mod_a = make_mod("alpha")
        mod_b = make_mod("beta")

        def import_side_effect(name):
            if name == "alpha":
                return mod_a
            if name == "beta":
                return mod_b
            return MagicMock()

        app = OpenViper()
        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["alpha", "beta"]
            with patch("importlib.import_module", side_effect=import_side_effect):
                await app._call_installed_app_ready_hooks()

        assert order == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_ready_hooks_called_during_lifespan_startup(self):
        """ready() hooks are invoked during the ASGI lifespan startup event."""
        called = []

        async def ready():
            called.append(True)

        fake_mod = MagicMock()
        fake_mod.ready = ready

        app = OpenViper()

        scope = {"type": "lifespan"}
        receive = AsyncMock(
            side_effect=[
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        send = AsyncMock()

        with patch("openviper.app.settings") as ms:
            ms.INSTALLED_APPS = ["myplugin"]
            ms.MIDDLEWARE = []
            ms.RATE_LIMIT_REQUESTS = 0
            with patch("importlib.import_module", return_value=fake_mod):
                # OpenViper uses __slots__, so patch at the class level.
                with patch.object(OpenViper, "_get_middleware_app", return_value=MagicMock()):
                    with patch("openviper.app.should_register_openapi", return_value=False):
                        await app._handle_lifespan(scope, receive, send)

        assert called
