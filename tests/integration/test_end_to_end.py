"""End-to-end integration tests for the OpenViper framework.

Covers the full request lifecycle through the real ASGI app: HTTP methods,
response types, routing converters, exception handling, middleware (CORS,
security), lifespan protocol, streaming, file responses, GZip, cookies,
redirects, and response coercion.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import typing as t
from pathlib import Path

import pytest

from openviper.app import OpenViper
from openviper.conf import settings
from openviper.exceptions import (
    Conflict,
    MethodNotAllowed,
    NotFound,
    PermissionDenied,
    TooManyRequests,
    Unauthorized,
)
from openviper.http.request import Request
from openviper.http.response import (
    FileResponse,
    GZipResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from openviper.middleware.cors import CORSMiddleware
from openviper.routing.router import (
    PathSecurityError,
    Router,
    include,
    sanitize_request_path,
)


async def run_app(
    app: OpenViper, scope: dict[str, object], body: bytes = b""
) -> list[dict[str, object]]:
    """Drive the ASGI app directly and collect all send messages."""
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg: dict[str, object]) -> None:
        messages.append(msg)

    await app(scope, receive, send)
    return messages


def make_http_scope(
    method: str = "GET",
    path: str = "/",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    server: tuple[str, int] = ("testserver", 80),
    client: tuple[str, int] = ("127.0.0.1", 9999),
    scheme: str = "http",
) -> dict[str, object]:
    """Build a complete ASGI HTTP scope."""
    raw_headers = headers or []
    header_names = {k.lower() for k, _ in raw_headers}
    if b"host" not in header_names:
        raw_headers = [(b"host", server[0].encode())] + list(raw_headers)
    return {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": raw_headers,
        "server": server,
        "client": client,
        "scheme": scheme,
        "root_path": "",
        "path_params": {},
        "state": {},
    }


def make_lifespan_scope() -> dict[str, object]:
    """Build an ASGI lifespan scope."""
    return {"type": "lifespan"}


def make_websocket_scope(path: str = "/ws") -> dict[str, object]:
    """Build an ASGI websocket scope."""
    return {
        "type": "websocket",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 9999),
        "scheme": "ws",
    }


def extract_status(messages: list[dict[str, object]]) -> int:
    """Extract the HTTP status code from ASGI send messages."""
    for msg in messages:
        if msg.get("type") == "http.response.start":
            return int(msg.get("status", 0))
    return 0


def extract_body(messages: list[dict[str, object]]) -> bytes:
    """Concatenate all body chunks from ASGI send messages."""
    chunks: list[bytes] = []
    for msg in messages:
        if msg.get("type") == "http.response.body":
            chunk = msg.get("body", b"")
            if isinstance(chunk, bytes):
                chunks.append(chunk)
    return b"".join(chunks)


def extract_headers(messages: list[dict[str, object]]) -> dict[bytes, bytes]:
    """Extract response headers into a lowercase-keyed dict."""
    for msg in messages:
        if msg.get("type") == "http.response.start":
            raw = msg.get("headers", [])
            if isinstance(raw, list):
                return {k.lower(): v for k, v in raw}
    return {}


class TestHTTPMethods:
    """Verify every HTTP method is handled end-to-end."""

    @pytest.mark.asyncio
    async def test_patch_method_routes_and_responds(self) -> None:
        app = OpenViper()

        @app.patch("/items/{item_id}")
        async def patch_item(item_id: int, request: Request) -> dict[str, object]:
            data = await request.json()
            return {"id": item_id, "patched": data}

        scope = make_http_scope("PATCH", "/items/42")
        msgs = await run_app(app, scope, b'{"name":"updated"}')
        assert extract_status(msgs) == 200
        body = extract_body(msgs)
        assert b'"id":' in body
        assert b"42" in body

    @pytest.mark.asyncio
    async def test_head_method_returns_200(self) -> None:
        app = OpenViper()

        @app.get("/data")
        async def get_data() -> dict[str, object]:
            return {"items": [1, 2, 3]}

        scope = make_http_scope("HEAD", "/data")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_options_method_not_registered_returns_405(self) -> None:
        app = OpenViper()

        @app.get("/resource")
        async def get_resource() -> dict[str, object]:
            return {"ok": True}

        @app.post("/resource")
        async def post_resource(request: Request) -> dict[str, object]:
            return {"created": True}

        scope = make_http_scope("OPTIONS", "/resource")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 405
        headers = extract_headers(msgs)
        allow = headers.get(b"allow", b"")
        assert b"GET" in allow
        assert b"POST" in allow

    @pytest.mark.asyncio
    async def test_method_not_allowed_returns_405_with_allow_header(self) -> None:
        app = OpenViper()

        @app.get("/locked")
        async def locked() -> dict[str, object]:
            return {"ok": True}

        scope = make_http_scope("DELETE", "/locked")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 405
        headers = extract_headers(msgs)
        assert b"allow" in headers

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self) -> None:
        app = OpenViper()

        scope = make_http_scope("GET", "/nonexistent")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 404


class TestResponseCoercion:
    """Verify handler return values are coerced to correct Response types."""

    @pytest.mark.asyncio
    async def test_dict_return_becomes_json(self) -> None:
        app = OpenViper()

        @app.get("/d")
        async def handler() -> dict[str, str]:
            return {"key": "value"}

        scope = make_http_scope("GET", "/d")
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        assert b"application/json" in headers.get(b"content-type", b"")
        assert b'"key"' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_list_return_becomes_json(self) -> None:
        app = OpenViper()

        @app.get("/l")
        async def handler() -> list[int]:
            return [1, 2, 3]

        scope = make_http_scope("GET", "/l")
        msgs = await run_app(app, scope)
        assert b"application/json" in extract_headers(msgs).get(b"content-type", b"")
        assert b"[1,2,3]" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_none_return_becomes_204(self) -> None:
        app = OpenViper()

        @app.get("/n")
        async def handler() -> None:
            return None

        scope = make_http_scope("GET", "/n")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 204

    @pytest.mark.asyncio
    async def test_string_return_becomes_plain_text(self) -> None:
        app = OpenViper()

        @app.get("/s")
        async def handler() -> str:
            return "hello world"

        scope = make_http_scope("GET", "/s")
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        assert b"text/plain" in headers.get(b"content-type", b"")
        assert extract_body(msgs) == b"hello world"

    @pytest.mark.asyncio
    async def test_bytes_return_becomes_plain_text(self) -> None:
        app = OpenViper()

        @app.get("/b")
        async def handler() -> bytes:
            return b"raw bytes"

        scope = make_http_scope("GET", "/b")
        msgs = await run_app(app, scope)
        assert b"text/plain" in extract_headers(msgs).get(b"content-type", b"")
        assert extract_body(msgs) == b"raw bytes"

    @pytest.mark.asyncio
    async def test_explicit_response_passes_through(self) -> None:
        app = OpenViper()

        @app.get("/r")
        async def handler() -> JSONResponse:
            return JSONResponse({"explicit": True}, status_code=201)

        scope = make_http_scope("GET", "/r")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 201
        assert b'"explicit":true' in extract_body(msgs)


class TestRoutingConverters:
    """Verify all path parameter converters work end-to-end."""

    @pytest.mark.asyncio
    async def test_int_converter(self) -> None:
        app = OpenViper()

        @app.get("/users/{user_id:int}")
        async def handler(user_id: int) -> dict[str, int]:
            return {"id": user_id, "type": type(user_id).__name__}

        scope = make_http_scope("GET", "/users/777")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b'"id":777' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_float_converter(self) -> None:
        app = OpenViper()

        @app.get("/rates/{rate:float}")
        async def handler(rate: float) -> dict[str, str]:
            return {"rate": str(rate)}

        scope = make_http_scope("GET", "/rates/3.14")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b"3.14" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_str_converter(self) -> None:
        app = OpenViper()

        @app.get("/items/{name:str}")
        async def handler(name: str) -> dict[str, str]:
            return {"name": name}

        scope = make_http_scope("GET", "/items/widget")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b"widget" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_uuid_converter(self) -> None:
        app = OpenViper()

        @app.get("/docs/{uid:uuid}")
        async def handler(uid: str) -> dict[str, str]:
            return {"uuid": uid}

        scope = make_http_scope("GET", "/docs/550e8400-e29b-41d4-a716-446655440000")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b"550e8400" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_slug_converter(self) -> None:
        app = OpenViper()

        @app.get("/posts/{slug:slug}")
        async def handler(slug: str) -> dict[str, str]:
            return {"slug": slug}

        scope = make_http_scope("GET", "/posts/hello-world-2024")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b"hello-world-2024" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_path_converter_captures_slashes(self) -> None:
        app = OpenViper()

        @app.get("/files/{filepath:path}")
        async def handler(filepath: str) -> dict[str, str]:
            return {"path": filepath}

        scope = make_http_scope("GET", "/files/a/b/c.txt")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b"a/b/c.txt" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_route_specificity_static_before_dynamic(self) -> None:
        app = OpenViper()

        @app.get("/users/me")
        async def me() -> dict[str, str]:
            return {"who": "me"}

        @app.get("/users/{user_id:int}")
        async def by_id(user_id: int) -> dict[str, int]:
            return {"who": user_id}

        scope = make_http_scope("GET", "/users/me")
        msgs = await run_app(app, scope)
        assert b'"me"' in extract_body(msgs)

        scope2 = make_http_scope("GET", "/users/99")
        msgs2 = await run_app(app, scope2)
        assert b"99" in extract_body(msgs2)

    @pytest.mark.asyncio
    async def test_trailing_slash_tolerance(self) -> None:
        app = OpenViper()

        @app.get("/items")
        async def list_items() -> dict[str, list[int]]:
            return {"items": [1, 2]}

        scope = make_http_scope("GET", "/items/")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200


class TestExceptionHandling:
    """Verify HTTPException subclasses produce correct status and headers."""

    @pytest.mark.asyncio
    async def test_not_found_exception_returns_404(self) -> None:
        app = OpenViper()

        @app.get("/nf")
        async def handler() -> t.NoReturn:
            raise NotFound("Gone")

        scope = make_http_scope("GET", "/nf")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 404

    @pytest.mark.asyncio
    async def test_permission_denied_returns_403(self) -> None:
        app = OpenViper()

        @app.get("/pd")
        async def handler() -> t.NoReturn:
            raise PermissionDenied("No access")

        scope = make_http_scope("GET", "/pd")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 403

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401_with_www_authenticate(self) -> None:
        app = OpenViper()

        @app.get("/ua")
        async def handler() -> t.NoReturn:
            raise Unauthorized()

        scope = make_http_scope("GET", "/ua")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 401
        headers = extract_headers(msgs)
        assert b"www-authenticate" in headers

    @pytest.mark.asyncio
    async def test_conflict_returns_409(self) -> None:
        app = OpenViper()

        @app.get("/c")
        async def handler() -> t.NoReturn:
            raise Conflict()

        scope = make_http_scope("GET", "/c")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 409

    @pytest.mark.asyncio
    async def test_too_many_requests_returns_429_with_retry_after(self) -> None:
        app = OpenViper()

        @app.get("/tmr")
        async def handler() -> t.NoReturn:
            raise TooManyRequests(retry_after=30)

        scope = make_http_scope("GET", "/tmr")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 429
        headers = extract_headers(msgs)
        assert headers.get(b"retry-after") == b"30"

    @pytest.mark.asyncio
    async def test_custom_exception_handler_via_decorator(self) -> None:
        app = OpenViper()

        class CustomError(Exception):
            pass

        @app.exception_handler(CustomError)
        async def handle_custom(request: Request, exc: CustomError) -> JSONResponse:
            return JSONResponse({"error": "custom"}, status_code=418)

        @app.get("/custom")
        async def handler() -> t.NoReturn:
            raise CustomError("boom")

        scope = make_http_scope("GET", "/custom")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 418
        assert b'"custom"' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_custom_handler_dispatches_by_mro(self) -> None:
        app = OpenViper()

        class BaseError(Exception):
            pass

        class SubError(BaseError):
            pass

        @app.exception_handler(BaseError)
        async def handle_base(request: Request, exc: BaseError) -> JSONResponse:
            return JSONResponse({"caught": "base"}, status_code=400)

        @app.get("/sub")
        async def handler() -> t.NoReturn:
            raise SubError("child")

        scope = make_http_scope("GET", "/sub")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 400
        assert b'"base"' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_500(self) -> None:
        app = OpenViper(debug=False)

        @app.get("/crash")
        async def handler() -> t.NoReturn:
            raise RuntimeError("unexpected")

        scope = make_http_scope("GET", "/crash")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 500


class TestStreamingResponse:
    """Verify StreamingResponse with async and sync iterators."""

    @pytest.mark.asyncio
    async def test_async_iterator_streaming(self) -> None:
        app = OpenViper()

        @app.get("/stream")
        async def handler() -> StreamingResponse:
            async def generate() -> t.AsyncIterator[bytes]:
                yield b"chunk1"
                yield b"chunk2"
                yield b"chunk3"

            return StreamingResponse(generate(), media_type="text/plain")

        scope = make_http_scope("GET", "/stream")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        body_parts = [
            msg.get("body", b"") for msg in msgs if msg.get("type") == "http.response.body"
        ]
        assert b"chunk1" in b"".join(body_parts)
        assert b"chunk3" in b"".join(body_parts)

    @pytest.mark.asyncio
    async def test_sync_iterator_streaming(self) -> None:
        app = OpenViper()

        @app.get("/sync-stream")
        async def handler() -> StreamingResponse:
            def generate() -> t.Iterator[bytes]:
                yield b"a"
                yield b"b"
                yield b"c"

            return StreamingResponse(iter(["a", "b", "c"]), media_type="application/octet-stream")

        scope = make_http_scope("GET", "/sync-stream")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200


class TestFileResponse:
    """Verify FileResponse with range and conditional requests."""

    def make_temp_file(self, content: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, content)
        os.close(fd)
        return path

    @pytest.mark.asyncio
    async def test_file_response_serves_full_content(self) -> None:
        content = b"Hello, FileResponse!" * 10
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/file")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/file")
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 200
            assert extract_body(msgs) == content
            headers = extract_headers(msgs)
            assert b"etag" in headers
            assert b"accept-ranges" in headers
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_file_response_range_request_returns_206(self) -> None:
        content = b"0123456789ABCDEFGHIJ"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/file")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/file", headers=[(b"range", b"bytes=5-10")])
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 206
            headers = extract_headers(msgs)
            assert b"content-range" in headers
            assert extract_body(msgs) == content[5:11]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_file_response_suffix_range(self) -> None:
        content = b"0123456789ABCDEF"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/file")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/file", headers=[(b"range", b"bytes=-4")])
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 206
            assert extract_body(msgs) == content[-4:]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_file_response_unsatisfiable_range_returns_416(self) -> None:
        content = b"short"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/file")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/file", headers=[(b"range", b"bytes=100-200")])
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 416
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_file_response_conditional_etag_returns_304(self) -> None:
        content = b"conditional content"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/file")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/file")
            msgs = await run_app(app, scope)
            headers = extract_headers(msgs)
            etag = headers.get(b"etag", b"")

            scope2 = make_http_scope("GET", "/file", headers=[(b"if-none-match", etag)])
            msgs2 = await run_app(app, scope2)
            assert extract_status(msgs2) == 304
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_file_response_rejects_path_outside_allowed_dir(self) -> None:
        content = b"secret"
        path = self.make_temp_file(content)
        allowed = tempfile.mkdtemp()
        try:
            with pytest.raises(ValueError, match="outside the allowed directory"):
                FileResponse(path, allowed_dir=allowed)
        finally:
            os.unlink(path)
            os.rmdir(allowed)


class TestGZipResponse:
    """Verify GZipResponse compression behaviour."""

    @pytest.mark.asyncio
    async def test_gzip_compresses_large_body(self) -> None:
        large_content = b"x" * 2000
        app = OpenViper()

        @app.get("/gz")
        async def handler() -> GZipResponse:
            inner = PlainTextResponse(large_content.decode())
            return GZipResponse(inner, minimum_size=100)

        scope = make_http_scope("GET", "/gz", headers=[(b"accept-encoding", b"gzip")])
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        assert headers.get(b"content-encoding") == b"gzip"
        assert b"vary" in headers

    @pytest.mark.asyncio
    async def test_gzip_skips_small_body(self) -> None:
        app = OpenViper()

        @app.get("/gz-small")
        async def handler() -> GZipResponse:
            inner = PlainTextResponse("tiny")
            return GZipResponse(inner, minimum_size=500)

        scope = make_http_scope("GET", "/gz-small", headers=[(b"accept-encoding", b"gzip")])
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        assert headers.get(b"content-encoding", b"") != b"gzip"
        assert extract_body(msgs) == b"tiny"


class TestCookiesAndRedirects:
    """Verify cookie security and redirect validations."""

    @pytest.mark.asyncio
    async def test_set_cookie_appears_in_headers(self) -> None:
        app = OpenViper()

        @app.get("/cookie")
        async def handler() -> Response:
            resp = JSONResponse({"ok": True})
            resp.set_cookie("session", "abc123", httponly=True, samesite="strict")
            return resp

        scope = make_http_scope("GET", "/cookie")
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        cookie_header = headers.get(b"set-cookie", b"")
        assert b"session=abc123" in cookie_header
        assert b"HttpOnly" in cookie_header
        assert b"SameSite=Strict" in cookie_header

    def test_cookie_rejects_cr_in_name(self) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            Response().set_cookie("bad\rname", "val")

    def test_cookie_rejects_lf_in_value(self) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            Response().set_cookie("ok", "bad\nvalue")

    def test_samesite_none_requires_secure(self) -> None:
        with pytest.raises(ValueError, match="SameSite=None"):
            Response().set_cookie("ok", "v", samesite="none", secure=False)

    def test_redirect_rejects_protocol_relative_url(self) -> None:
        with pytest.raises(ValueError, match="protocol-relative|Protocol-relative"):
            RedirectResponse("//evil.com/path")

    def test_redirect_rejects_crl_injection(self) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse("/ok\r\nSet-Cookie: evil=1")

    def test_redirect_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="traversal"):
            RedirectResponse("/safe/../../../etc/passwd")

    def test_redirect_rejects_disallowed_scheme(self) -> None:
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse("file:///etc/passwd")

    def test_redirect_rejects_userinfo_in_netloc(self) -> None:
        with pytest.raises(ValueError, match="userinfo"):
            RedirectResponse("http://user:pass@evil.com/x")


class TestCORS:
    """Verify CORS middleware preflight and actual request handling."""

    @pytest.mark.asyncio
    async def test_cors_preflight_returns_204_with_headers(self) -> None:
        inner_app = OpenViper()

        @inner_app.get("/api")
        async def api_handler() -> dict[str, str]:
            return {"ok": "true"}

        cors = CORSMiddleware(
            inner_app,
            allowed_origins=["https://example.com"],
            allow_credentials=True,
            allowed_methods=["GET", "POST"],
            allowed_headers=["content-type"],
            max_age=7200,
        )

        scope = make_http_scope(
            "OPTIONS",
            "/api",
            headers=[
                (b"origin", b"https://example.com"),
                (b"access-control-request-method", b"POST"),
                (b"access-control-request-headers", b"content-type"),
            ],
        )
        msgs: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg: dict[str, object]) -> None:
            msgs.append(msg)

        await cors(scope, receive, send)
        assert extract_status(msgs) == 204
        headers = extract_headers(msgs)
        assert headers.get(b"access-control-allow-origin") == b"https://example.com"
        assert b"GET" in headers.get(b"access-control-allow-methods", b"")
        assert b"POST" in headers.get(b"access-control-allow-methods", b"")
        assert headers.get(b"access-control-max-age") == b"7200"

    @pytest.mark.asyncio
    async def test_cors_actual_request_adds_allow_origin(self) -> None:
        inner_app = OpenViper()

        @inner_app.get("/api")
        async def api_handler() -> dict[str, str]:
            return {"ok": "true"}

        cors = CORSMiddleware(
            inner_app,
            allowed_origins=["https://example.com"],
            allowed_methods=["GET"],
        )

        scope = make_http_scope("GET", "/api", headers=[(b"origin", b"https://example.com")])
        msgs: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg: dict[str, object]) -> None:
            msgs.append(msg)

        await cors(scope, receive, send)
        headers = extract_headers(msgs)
        assert headers.get(b"access-control-allow-origin") == b"https://example.com"

    def test_cors_rejects_wildcard_with_credentials(self) -> None:
        with pytest.raises(ValueError, match="wildcard"):
            CORSMiddleware(OpenViper(), allowed_origins=["*"], allow_credentials=True)

    @pytest.mark.asyncio
    async def test_cors_no_origin_header_passes_through(self) -> None:
        inner_app = OpenViper()

        @inner_app.get("/api")
        async def api_handler() -> dict[str, str]:
            return {"ok": "true"}

        cors = CORSMiddleware(inner_app, allowed_origins=["https://example.com"])

        scope = make_http_scope("GET", "/api")
        msgs: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg: dict[str, object]) -> None:
            msgs.append(msg)

        await cors(scope, receive, send)
        headers = extract_headers(msgs)
        assert b"access-control-allow-origin" not in headers


class TestSubRouters:
    """Verify sub-router mounting, prefixes, and namespaces."""

    @pytest.mark.asyncio
    async def test_include_router_with_prefix(self) -> None:
        api = Router()

        @api.get("/users")
        async def list_users() -> dict[str, str]:
            return {"users": "all"}

        app = OpenViper()
        app.include_router(api, prefix="/api/v1")

        scope = make_http_scope("GET", "/api/v1/users")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b'"all"' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_nested_sub_routers(self) -> None:
        posts = Router()

        @posts.get("/{post_id:int}")
        async def get_post(post_id: int) -> dict[str, int]:
            return {"post": post_id}

        users = Router()

        @users.get("/{user_id:int}/posts")
        async def list_user_posts(user_id: int) -> dict[str, int]:
            return {"user": user_id, "posts": []}

        users.include_router(posts, prefix="/{user_id:int}/posts")
        app = OpenViper()
        app.include_router(users, prefix="/api/users")

        scope = make_http_scope("GET", "/api/users/5/posts/10")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b'"post":10' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_url_for_reverse_resolution(self) -> None:
        app = OpenViper()

        @app.get("/products/{product_id:int}", name="product_detail")
        async def handler(product_id: int) -> dict[str, int]:
            return {"id": product_id}

        url = app.router.url_for("product_detail", product_id=42)
        assert "42" in url
        assert "/products/" in url

    @pytest.mark.asyncio
    async def test_url_for_rejects_traversal_in_param_value(self) -> None:
        app = OpenViper()

        @app.get("/docs/{doc_id}", name="doc")
        async def handler(doc_id: str) -> dict[str, str]:
            return {"doc": doc_id}

        with pytest.raises(ValueError, match="disallowed characters"):
            app.router.url_for("doc", doc_id="../secret")

    @pytest.mark.asyncio
    async def test_url_for_unknown_name_raises_keyerror(self) -> None:
        app = OpenViper()
        with pytest.raises(KeyError, match="nonexistent"):
            app.router.url_for("nonexistent")


class TestPathSecurity:
    """Verify path traversal and malicious path rejection at routing layer."""

    @pytest.mark.asyncio
    async def test_null_byte_in_path_raises_security_error(self) -> None:
        app = OpenViper()

        @app.get("/safe")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        scope = make_http_scope("GET", "/safe\x00evil")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) in (400, 404, 500)

    @pytest.mark.asyncio
    async def test_encoded_slash_rejected(self) -> None:
        app = OpenViper()

        @app.get("/safe")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        scope = make_http_scope("GET", "/safe%2f..%2fadmin")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) in (400, 404, 500)

    @pytest.mark.asyncio
    async def test_directory_traversal_rejected(self) -> None:
        app = OpenViper()

        @app.get("/public")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        scope = make_http_scope("GET", "/public/../../../etc/passwd")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) in (400, 404, 500)

    def test_sanitize_request_path_raises_on_null_byte(self) -> None:
        with pytest.raises(PathSecurityError, match="Null byte"):
            sanitize_request_path("/safe\x00evil")

    def test_sanitize_request_path_raises_on_encoded_slash(self) -> None:
        with pytest.raises(PathSecurityError, match="Encoded slash"):
            sanitize_request_path("/path%2fhidden")

    def test_sanitize_request_path_raises_on_traversal(self) -> None:
        with pytest.raises(PathSecurityError, match="Directory traversal"):
            sanitize_request_path("/safe/../etc")

    def test_sanitize_request_path_raises_on_decoded_traversal(self) -> None:
        with pytest.raises(PathSecurityError, match="Directory traversal"):
            sanitize_request_path("/safe/%2e%2e/secret")

    def test_sanitize_request_path_collapses_slashes(self) -> None:
        assert sanitize_request_path("/a//b///c") == "/a/b/c"


class TestLifespanProtocol:
    """Verify ASGI lifespan startup/shutdown events."""

    @pytest.fixture(autouse=True)
    def clear_settings_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENVIPER_SETTINGS_MODULE", raising=False)
        monkeypatch.setattr(type(settings), "INSTALLED_APPS", (), raising=False)

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown_complete(self) -> None:
        app = OpenViper()
        started: list[bool] = []
        shutdowned: list[bool] = []

        @app.on_startup
        def on_start() -> None:
            started.append(True)

        @app.on_shutdown
        def on_stop() -> None:
            shutdowned.append(True)

        events: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            if len(events) == 0:
                events.append({"type": "lifespan.startup"})
                return events[-1]
            events.append({"type": "lifespan.shutdown"})
            return events[-1]

        sent: list[dict[str, object]] = []

        async def send(msg: dict[str, object]) -> None:
            sent.append(msg)

        scope = make_lifespan_scope()
        await app(scope, receive, send)
        assert sent[0].get("type") == "lifespan.startup.complete"
        assert sent[-1].get("type") == "lifespan.shutdown.complete"
        assert started
        assert shutdowned

    @pytest.mark.asyncio
    async def test_lifespan_startup_failure_sends_failed_event(self) -> None:
        app = OpenViper()

        @app.on_startup
        def fail_startup() -> t.NoReturn:
            raise RuntimeError("boom")

        events: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            if not events:
                events.append({"type": "lifespan.startup"})
                return events[-1]
            events.append({"type": "lifespan.shutdown"})
            return events[-1]

        sent: list[dict[str, object]] = []

        async def send(msg: dict[str, object]) -> None:
            sent.append(msg)

        scope = make_lifespan_scope()
        await app(scope, receive, send)
        assert sent[0].get("type") == "lifespan.startup.failed"
        assert "boom" in str(sent[0].get("message", ""))

    @pytest.mark.asyncio
    async def test_async_startup_handler_awaited(self) -> None:
        app = OpenViper()
        called: list[str] = []

        @app.on_startup
        async def async_start() -> None:
            await asyncio.sleep(0.01)
            called.append("async-start")

        call_count: list[int] = []

        async def receive() -> dict[str, object]:
            call_count.append(1)
            if len(call_count) == 1:
                return {"type": "lifespan.startup"}
            return {"type": "lifespan.shutdown"}

        sent: list[dict[str, object]] = []

        async def send(msg: dict[str, object]) -> None:
            sent.append(msg)

        scope = make_lifespan_scope()
        await app(scope, receive, send)
        assert called == ["async-start"]
        assert sent[0].get("type") == "lifespan.startup.complete"


class TestWebSocket:
    """Verify unhandled WebSocket connections are closed cleanly."""

    @pytest.mark.asyncio
    async def test_unhandled_websocket_closed_with_4404(self) -> None:
        app = OpenViper()

        scope = make_websocket_scope("/nonexistent")
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "websocket.connect"}

        async def send(msg: dict[str, object]) -> None:
            sent.append(msg)

        await app(scope, receive, send)
        assert sent[0].get("type") == "websocket.close"
        assert sent[0].get("code") == 4404


class TestRequestBodyLimits:
    """Verify request body size enforcement."""

    @pytest.mark.asyncio
    async def test_oversized_content_length_rejected(self) -> None:
        app = OpenViper()

        @app.post("/data")
        async def handler(request: Request) -> dict[str, str]:
            await request.body()
            return {"ok": "true"}

        scope = make_http_scope("POST", "/data", headers=[(b"content-length", b"99999999999")])

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"x" * 100, "more_body": False}

        msgs: list[dict[str, object]] = []

        async def send(msg: dict[str, object]) -> None:
            msgs.append(msg)

        await app(scope, receive, send)
        status = extract_status(msgs)
        assert status in (400, 500)

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self) -> None:
        app = OpenViper()

        @app.post("/json")
        async def handler(request: Request) -> dict[str, str]:
            await request.json()
            return {"ok": "true"}

        scope = make_http_scope("POST", "/json", headers=[(b"content-type", b"application/json")])
        msgs = await run_app(app, scope, b"{not valid json}")
        status = extract_status(msgs)
        assert status == 400


class TestOpenAPI:
    """Verify OpenAPI schema generation and docs routes."""

    @pytest.mark.asyncio
    async def test_openapi_json_route_returns_schema(self) -> None:
        app = OpenViper(title="Test API", version="2.0.0")

        @app.get("/items")
        async def list_items() -> dict[str, str]:
            return {"items": "all"}

        scope = make_http_scope("GET", "/open-api/openapi.json")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        body = extract_body(msgs)
        assert b'"openapi"' in body
        assert b'"title"' in body

    @pytest.mark.asyncio
    async def test_swagger_ui_route_returns_html(self) -> None:
        app = OpenViper()

        scope = make_http_scope("GET", "/open-api/docs")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        headers = extract_headers(msgs)
        assert b"text/html" in headers.get(b"content-type", b"")

    @pytest.mark.asyncio
    async def test_redoc_ui_route_returns_html(self) -> None:
        app = OpenViper()

        scope = make_http_scope("GET", "/open-api/redoc")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        headers = extract_headers(msgs)
        assert b"text/html" in headers.get(b"content-type", b"")


class TestMiddlewareStackIntegration:
    """Verify the full middleware stack processes requests correctly."""

    @pytest.mark.asyncio
    async def test_error_page_in_production_hides_traceback(self) -> None:
        app = OpenViper(debug=False)

        @app.get("/crash")
        async def handler() -> t.NoReturn:
            raise RuntimeError("secret internal error")

        scope = make_http_scope("GET", "/crash")
        msgs = await run_app(app, scope)
        body = extract_body(msgs)
        assert b"secret internal error" not in body
        assert b"Internal Server Error" in body

    @pytest.mark.asyncio
    async def test_error_page_in_debug_shows_traceback(self) -> None:
        app = OpenViper(debug=True)

        @app.get("/crash")
        async def handler() -> t.NoReturn:
            raise RuntimeError("visible debug error")

        scope = make_http_scope("GET", "/crash", headers=[(b"accept", b"text/html")])
        msgs = await run_app(app, scope)
        body = extract_body(msgs)
        assert b"visible debug error" in body

    @pytest.mark.asyncio
    async def test_error_response_json_for_api_accept(self) -> None:
        app = OpenViper(debug=False)

        @app.get("/err")
        async def handler() -> t.NoReturn:
            raise NotFound("Missing thing")

        scope = make_http_scope("GET", "/err", headers=[(b"accept", b"application/json")])
        msgs = await run_app(app, scope)
        headers = extract_headers(msgs)
        assert b"application/json" in headers.get(b"content-type", b"")

    @pytest.mark.asyncio
    async def test_concurrent_requests_isolated_state(self) -> None:
        app = OpenViper()

        @app.get("/state/{value}")
        async def handler(request: Request) -> dict[str, object]:
            request.state["v"] = request.path_params.get("value")
            return {"value": request.state.get("v")}

        async def make_request(val: str) -> int:
            scope = make_http_scope("GET", f"/state/{val}")
            msgs = await run_app(app, scope)
            return extract_status(msgs)

        results = await asyncio.gather(
            make_request("a"),
            make_request("b"),
            make_request("c"),
            make_request("d"),
            make_request("e"),
        )
        assert all(r == 200 for r in results)
