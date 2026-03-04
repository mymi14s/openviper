import asyncio
import json

import pytest
from pydantic import BaseModel

from openviper.app import OpenViper
from openviper.exceptions import HTTPException, NotFound
from openviper.http.request import Request
from openviper.http.response import HTMLResponse, JSONResponse, PlainTextResponse, Response
from openviper.routing.router import Router
from tests.factories.app_factory import create_application


@pytest.mark.asyncio
async def test_app_initialization():
    app = OpenViper(
        title="Test App",
        version="1.2.3",
        openapi_url="/custom-openapi.json",
        docs_url="/custom-docs",
        redoc_url="/custom-redoc",
    )
    assert app.title == "Test App"
    assert app.version == "1.2.3"
    assert app.openapi_url == "/custom-openapi.json"
    assert app.docs_url == "/custom-docs"
    assert app.redoc_url == "/custom-redoc"


@pytest.mark.asyncio
async def test_app_route_decorators():
    app = create_application()

    @app.get("/get")
    async def get_test():
        return "get"

    @app.post("/post")
    async def post_test():
        return "post"

    @app.put("/put")
    async def put_test():
        return "put"

    @app.patch("/patch")
    async def patch_test():
        return "patch"

    @app.delete("/delete")
    async def delete_test():
        return "delete"

    @app.options("/options")
    async def options_test():
        return "options"

    @app.route("/route", methods=["GET", "POST"])
    async def route_test():
        return "route"

    routes = [route.path for route in app.router.routes]
    for path in ["/get", "/post", "/put", "/patch", "/delete", "/options", "/route"]:
        assert path in routes


@pytest.mark.asyncio
async def test_app_include_router():
    app = create_application()
    sub_router = Router()

    @sub_router.get("/sub")
    async def sub():
        return "sub"

    app.include_router(sub_router, prefix="/api")
    route, _ = app.router.resolve("GET", "/api/sub")
    assert route.path == "/api/sub"

    app.include_router(sub_router)  # no prefix
    route, _ = app.router.resolve("GET", "/sub")
    assert route.path == "/sub"


@pytest.mark.asyncio
async def test_app_exception_handling():
    app = create_application()

    @app.exception_handler(ValueError)
    async def handle_value_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    from tests.factories.http_factory import create_request

    request = create_request()

    response = await app._handle_exception(request, ValueError("bad value"))
    assert response.status_code == 400
    assert json.loads(response.body) == {"error": "bad value"}

    # Test HTTP Exception
    response = await app._handle_exception(
        request, HTTPException(status_code=403, detail="Forbidden")
    )
    assert response.status_code == 403
    assert json.loads(response.body) == {"detail": "Forbidden"}

    # Test unhandled generic exception JSON
    response = await app._handle_exception(request, Exception("Crash"))
    assert response.status_code == 500
    assert b"Crash" in response.body


@pytest.mark.asyncio
async def test_app_error_response_html_vs_json():
    app = OpenViper(debug=True)
    from tests.factories.http_factory import create_request

    # JSON request
    req_json = create_request(headers=[(b"accept", b"application/json")])
    resp_json = app._create_error_response(req_json, {"detail": "Error", "traceback": ["tb"]}, 500)
    assert isinstance(resp_json, JSONResponse)

    # HTML request
    req_html = create_request(headers=[(b"accept", b"text/html")])
    resp_html = app._create_error_response(
        req_html, {"detail": "Error", "type": "ValueError", "traceback": ["line 1"]}, 500
    )
    assert isinstance(resp_html, HTMLResponse)
    assert b"ValueError" in resp_html.body
    assert b"line 1" in resp_html.body


@pytest.mark.asyncio
async def test_app_openapi_schema_generation():
    app = create_application()
    schema = app._get_openapi_schema()
    assert "openapi" in schema
    assert schema["info"]["title"] == app.title

    app.invalidate_openapi_schema()
    assert app._openapi_schema is None


@pytest.mark.asyncio
async def test_app_middleware_builder():
    app = create_application()
    app.debug = False  # trigger static disabled logs

    # 225 line: settings.MIDDLEWARE failing
    app._build_middleware_stack()  # standard build

    # Force settings mock
    from unittest.mock import patch

    with patch("openviper.app.settings") as mock_settings:
        mock_settings.MIDDLEWARE = ["invalid.noexist.Mw"]
        mock_settings.RATE_LIMIT_REQUESTS = 100
        app._build_middleware_stack()

    app._extra_middleware = ["openviper.middleware.cors.CORSMiddleware"]
    # Should warn on invalid string
    app._extra_middleware.append("invalidmodule")  # fails rsplit unpacking
    app._extra_middleware.append("invalid.module.Class")  # triggers Exception on import
    try:
        app._build_middleware_stack()
    except ValueError:
        pass


@pytest.mark.asyncio
async def test_app_call_handler_coercion():
    app = create_application()

    class MockModel(BaseModel):
        name: str

    handler_pydantic = lambda: MockModel(name="test")
    resp = await app._call_handler(handler_pydantic, None)
    assert json.loads(resp.body) == {"name": "test"}

    handler_list = lambda: [{"id": 1}]
    resp = await app._call_handler(handler_list, None)
    assert json.loads(resp.body) == [{"id": 1}]

    handler_resp = lambda: PlainTextResponse("direct")
    resp = await app._call_handler(handler_resp, None)
    assert resp.body == b"direct"


@pytest.mark.asyncio
async def test_app_has_custom_root_route():
    app = create_application()
    assert not app._has_custom_root_route()

    @app.get("/")
    async def index():
        return "ok"

    assert app._has_custom_root_route()


@pytest.mark.asyncio
async def test_handle_websocket():
    app = create_application()
    sent_messages = []

    async def receive():
        return {}

    async def send(msg):
        sent_messages.append(msg)

    await app._handle_websocket({"type": "websocket"}, receive, send)
    assert sent_messages == [{"type": "websocket.close", "code": 1011}]


@pytest.mark.asyncio
async def test_handle_lifespan_failures():
    app = create_application()

    @app.on_startup
    async def broken_startup():
        raise ValueError("Startup fail")

    sent_messages = []

    async def send(msg):
        sent_messages.append(msg)

    async def receive_start():
        return {"type": "lifespan.startup"}

    await app._handle_lifespan({"type": "lifespan"}, receive_start, send)
    assert sent_messages[-1] == {"type": "lifespan.startup.failed", "message": "Startup fail"}

    sent_messages.clear()

    @app.on_shutdown
    async def broken_shutdown():
        raise ValueError("Shutdown fail")

    async def receive_stop():
        return {"type": "lifespan.shutdown"}

    await app._handle_lifespan({"type": "lifespan"}, receive_stop, send)
    assert sent_messages[-1] == {"type": "lifespan.shutdown.failed", "message": "Shutdown fail"}


def test_app_run_wrapper():
    app = create_application()
    from unittest.mock import patch

    with patch("openviper.app.uvicorn.run") as mock_run:
        app.run(host="0.0.0.0", port=9000, reload=False, workers=2)
        mock_run.assert_called_once_with(
            app, host="0.0.0.0", port=9000, reload=False, log_level="info", workers=2
        )


def test_app_repr():
    app = create_application(title="ReprApp")
    assert repr(app) == "OpenViper(title='ReprApp', routes=3)"


@pytest.mark.asyncio
async def test_app_openapi_routes(test_client):
    app = create_application()

    resp_schema = await test_client.get("/open-api/openapi.json")
    assert resp_schema.status_code == 200

    resp_docs = await test_client.get("/open-api/docs")
    assert resp_docs.status_code == 200
    assert "Swagger" in resp_docs.text

    resp_redoc = await test_client.get("/open-api/redoc")
    assert resp_redoc.status_code == 200
    assert "ReDoc" in resp_redoc.text


# ---------------------------------------------------------------------------
# _coerce_response — uncovered branches (lines 417, 419, 423)
# ---------------------------------------------------------------------------


def test_coerce_response_none_returns_204():
    """Line 417: None → Response with status_code=204."""
    app = create_application()
    result = app._coerce_response(None)
    assert result.status_code == 204
    assert result.body == b""


def test_coerce_response_string_returns_plain_text():
    """Line 419: str → PlainTextResponse."""
    app = create_application()
    result = app._coerce_response("hello world")
    assert isinstance(result, PlainTextResponse)
    assert b"hello world" in result.body


def test_coerce_response_bytes_returns_plain_text():
    """Line 419: bytes → PlainTextResponse."""
    app = create_application()
    result = app._coerce_response(b"raw bytes")
    assert isinstance(result, PlainTextResponse)
    assert b"raw bytes" in result.body


def test_coerce_response_fallback_json():
    """Line 423: non-dict/list/None/str/bytes value → fallback JSONResponse."""
    app = create_application()
    # An integer hits the final fallback `return JSONResponse(result)`
    result = app._coerce_response(42)
    assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# _core_app — websocket dispatch (lines 350-352)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_core_app_dispatches_websocket():
    """Lines 350-352: _core_app dispatches scope['type']=='websocket' to _handle_websocket."""
    app = create_application()
    sent = []

    async def receive():
        return {}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "websocket", "path": "/ws", "headers": []}
    await app._core_app(scope, receive, send)
    # _handle_websocket closes with 1011 when no WS route found
    assert any(m.get("type") == "websocket.close" for m in sent)


# ---------------------------------------------------------------------------
# _build_middleware_stack — valid MIDDLEWARE entry (line 276)
# ---------------------------------------------------------------------------


def test_build_middleware_stack_valid_middleware():
    """Line 276: valid cls is appended to raw_middleware."""
    from unittest.mock import patch

    app = create_application()
    app.debug = False

    with patch("openviper.app.settings") as ms:
        ms.MIDDLEWARE = ["openviper.middleware.cors.CORSMiddleware"]
        ms.RATE_LIMIT_REQUESTS = 0
        # Should not raise; valid middleware is resolved and appended
        result = app._build_middleware_stack()
    assert result is not None


# ---------------------------------------------------------------------------
# _handle_http — per-route middleware (line 367)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_http_per_route_middleware():
    """Line 367: per-route middleware wraps the handler."""
    from unittest.mock import MagicMock, patch

    app = create_application()
    middleware_called = []

    def tracking_middleware(next_handler):
        async def wrapped(request):
            middleware_called.append(True)
            return await next_handler(request)

        return wrapped

    @app.get("/mw-test", middlewares=[tracking_middleware])
    async def mw_handler(request):
        return JSONResponse({"ok": True})

    from tests.factories.http_factory import create_request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mw-test",
        "headers": [],
        "query_string": b"",
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    await app._handle_http(scope, receive, send)
    assert middleware_called == [True]
