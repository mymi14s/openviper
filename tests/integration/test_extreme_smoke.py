"""Extreme smoke tests for the OpenViper framework.

Pushes the framework to its limits with adversarial inputs, high
concurrency, edge-case payloads, and security boundary probes.
Every test uses the real ASGI app - no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import typing as t
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from openviper.app import OpenViper
from openviper.conf import settings
from openviper.exceptions import HTTPException
from openviper.http.request import MAX_BODY_SIZE, Request, is_host_allowed, validate_host_port
from openviper.http.response import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
    is_allowed_redirect_host,
    strip_host_port,
)
from openviper.routing.router import (
    CONVERTERS,
    PathSecurityError,
    Route,
    Router,
    compile_path,
    normalize_path,
    sanitize_request_path,
)


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


class TestAdversarialPaths:
    """Probe routing with malicious and edge-case path inputs."""

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "/../../../etc/passwd",
            "/safe/../../etc/shadow",
            "/%2e%2e/secret",
            "/safe%2f..%2fadmin",
            "/%252e%252e/escape",
            "/\x00null/byte",
            "/safe/\x00",
            "//double/slash",
            "/a//b///c",
            "/unicode/\xff\xfe",
        ],
    )
    @pytest.mark.asyncio
    async def test_malicious_paths_do_not_crash_app(self, malicious_path: str) -> None:
        app = OpenViper()

        @app.get("/safe")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        scope = make_http_scope("GET", malicious_path)
        msgs = await run_app(app, scope)
        status = extract_status(msgs)
        assert status in (200, 301, 302, 307, 400, 404, 500)

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "",
            "/a",
            "/a/b/c/d/e/f/g/h",
            "/users/0",
            "/users/999999999999",
            "/users/-1",
            "/users/abc",
        ],
    )
    @pytest.mark.asyncio
    async def test_edge_case_paths_handled_gracefully(self, path: str) -> None:
        app = OpenViper()

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"page": "root"}

        @app.get("/users/{user_id:int}")
        async def user_detail(user_id: int) -> dict[str, int]:
            return {"id": user_id}

        scope = make_http_scope("GET", path)
        msgs = await run_app(app, scope)
        status = extract_status(msgs)
        assert status in (200, 404, 405)

    def test_sanitize_request_path_single_decoded_traversal_caught(self) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/safe/%2e%2e/escape")

    def test_sanitize_request_path_rejects_mixed_case_encoded_slash(self) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/safe/%2F")

    def test_normalize_path_collapses_multiple_slashes(self) -> None:
        assert normalize_path("/a//b///c") == "/a/b/c"

    def test_normalize_path_preserves_single_slash(self) -> None:
        assert normalize_path("/a/b") == "/a/b"

    def test_compile_path_caches_identical_patterns(self) -> None:
        regex1, converters1 = compile_path("/items/{id:int}")
        regex2, converters2 = compile_path("/items/{id:int}")
        assert regex1 is regex2
        assert converters1 is converters2

    def test_compile_path_rejects_unknown_converter(self) -> None:
        with pytest.raises(ValueError, match="Unknown path converter"):
            compile_path("/items/{id:bogus}")

    @pytest.mark.parametrize(
        "invalid_param_name",
        ["{123}", "{with-dash}", "{has spaces}", "{dot.test}", "{1abc}"],
    )
    def test_route_rejects_invalid_param_name(self, invalid_param_name: str) -> None:
        with pytest.raises(ValueError, match="Invalid path parameter name"):
            Route(
                path=f"/items/{invalid_param_name}",
                methods={"GET"},
                handler=lambda: None,
                name="test",
            )


class TestHostHeaderValidation:
    """Probe Host header injection defenses."""

    @pytest.mark.parametrize(
        "raw_host,expected",
        [
            ("localhost", True),
            ("localhost:8000", True),
            ("example.com", True),
            ("example.com:443", True),
            ("192.168.1.1", True),
            ("[::1]:8000", False),
            ("[::1]", False),
            ("invalid:99999", False),
            ("invalid:abc", False),
            ("", False),
            ("host with spaces", False),
            ("host\r\nInject", False),
            ("host\x00null", False),
        ],
    )
    def test_validate_host_port(self, raw_host: str, expected: bool) -> None:
        assert validate_host_port(raw_host) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("localhost", "localhost"),
            ("localhost:8000", "localhost"),
            ("example.com:443", "example.com"),
            ("[::1]:8000", "::1"),
            ("[::1]", "::1"),
            ("nopath", "nopath"),
        ],
    )
    def test_strip_host_port(self, raw: str, expected: str) -> None:
        assert strip_host_port(raw) == expected

    def test_is_allowed_redirect_host_wildcard(self) -> None:
        assert is_allowed_redirect_host("evil.com", ["*"]) is True

    def test_is_allowed_redirect_host_exact_match(self) -> None:
        assert is_allowed_redirect_host("example.com", ["example.com"]) is True
        assert is_allowed_redirect_host("evil.com", ["example.com"]) is False

    def test_is_allowed_redirect_host_subdomain(self) -> None:
        assert is_allowed_redirect_host("api.example.com", [".example.com"]) is True
        assert is_allowed_redirect_host("example.com", [".example.com"]) is True
        assert is_allowed_redirect_host("notevil.com", [".example.com"]) is False

    def test_is_allowed_redirect_host_empty(self) -> None:
        assert is_allowed_redirect_host("", ["example.com"]) is False

    def test_is_allowed_redirect_host_case_insensitive(self) -> None:
        assert is_allowed_redirect_host("Example.COM", ["example.com"]) is True
        assert is_allowed_redirect_host("API.Example.com", [".example.com"]) is True

    def test_is_allowed_redirect_host_trailing_dot(self) -> None:
        assert is_allowed_redirect_host("example.com.", ["example.com"]) is True


class TestRedirectSecurity:
    """Exhaustively probe RedirectResponse for open-redirect vectors."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "ftp://evil.com/file",
            "ldap://evil.com",
            "gopher://evil.com",
        ],
    )
    def test_redirect_rejects_dangerous_schemes(self, url: str) -> None:
        with pytest.raises(ValueError, match="disallowed scheme|traversal"):
            RedirectResponse(url)

    @pytest.mark.parametrize(
        "url",
        [
            "/safe/../../../etc/passwd",
            "/safe/%2e%2e/secret",
            "/safe/%252e%252e/double",
            "/safe/..%2f..%2f",
            "/safe/%5c..%5c..",
        ],
    )
    def test_redirect_rejects_traversal_variants(self, url: str) -> None:
        with pytest.raises(ValueError, match="traversal"):
            RedirectResponse(url)

    @pytest.mark.parametrize(
        "url",
        [
            "/safe\r\nSet-Cookie: evil=1",
            "/safe\rX-Injected: yes",
            "/safe\nSet-Cookie: evil=1",
            "/safe\r\n\r\n<html>",
        ],
    )
    def test_redirect_rejects_crlf_injection(self, url: str) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse(url)

    @pytest.mark.parametrize(
        "url",
        [
            "//evil.com",
            "//evil.com/path",
            "//user@evil.com/x",
        ],
    )
    def test_redirect_rejects_protocol_relative(self, url: str) -> None:
        with pytest.raises(ValueError, match="protocol-relative|Protocol-relative"):
            RedirectResponse(url)

    def test_redirect_allows_safe_relative_path(self) -> None:
        resp = RedirectResponse("/safe/redirect")
        assert resp.status_code == 307
        assert resp.headers.get("location") == "/safe/redirect"

    def test_redirect_allows_safe_absolute_url(self) -> None:
        with (
            patch.object(
                type(settings), "ALLOWED_REDIRECT_HOSTS",
                ("example.com",), create=True,
            ),
            patch.object(
                type(settings), "ALLOWED_HOSTS",
                ("example.com",), create=True,
            ),
        ):
            resp = RedirectResponse("https://example.com/path")
            assert resp.status_code == 307

    def test_redirect_rejects_unauthorized_external_host(self) -> None:
        with (
            patch.object(
                type(settings), "ALLOWED_REDIRECT_HOSTS",
                ("trusted.com",), create=True,
            ),
            patch.object(
                type(settings), "ALLOWED_HOSTS",
                ("trusted.com",), create=True,
            ),
        ):
            with pytest.raises(ValueError, match="not allowed"):
                RedirectResponse("https://evil.com/path")


class TestCookieSecurity:
    """Exhaustively probe cookie handling for injection vectors."""

    @pytest.mark.parametrize("name", ["bad\rname", "bad\nname", "bad\r\nname"])
    def test_cookie_rejects_crlf_in_name(self, name: str) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            Response().set_cookie(name, "value")

    @pytest.mark.parametrize("value", ["bad\rvalue", "bad\nvalue", "bad\r\nvalue"])
    def test_cookie_rejects_crlf_in_value(self, value: str) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            Response().set_cookie("name", value)

    def test_cookie_samesite_none_without_secure_raises(self) -> None:
        with pytest.raises(ValueError, match="SameSite=None"):
            Response().set_cookie("name", "v", samesite="none", secure=False)

    def test_cookie_samesite_none_with_secure_ok(self) -> None:
        resp = Response()
        resp.set_cookie("name", "v", samesite="none", secure=True)
        cookie = resp.headers.get("set-cookie", "")
        assert "SameSite=None" in cookie
        assert "Secure" in cookie

    @pytest.mark.parametrize("samesite", ["lax", "strict", "none", "Lax", "Strict"])
    def test_cookie_samesite_capitalized(self, samesite: str) -> None:
        resp = Response()
        if samesite.lower() == "none":
            resp.set_cookie("name", "v", samesite=samesite, secure=True)
        else:
            resp.set_cookie("name", "v", samesite=samesite)
        cookie = resp.headers.get("set-cookie", "")
        assert f"SameSite={samesite.capitalize()}" in cookie

    def test_delete_cookie_sets_max_age_zero(self) -> None:
        resp = Response()
        resp.delete_cookie("session")
        cookie = resp.headers.get("set-cookie", "")
        assert "Max-Age=0" in cookie

    def test_cookie_httponly_flag(self) -> None:
        resp = Response()
        resp.set_cookie("name", "v", httponly=True)
        assert "HttpOnly" in resp.headers.get("set-cookie", "")

    def test_cookie_secure_flag(self) -> None:
        resp = Response()
        resp.set_cookie("name", "v", secure=True)
        assert "Secure" in resp.headers.get("set-cookie", "")

    def test_cookie_domain_and_path(self) -> None:
        resp = Response()
        resp.set_cookie("name", "v", domain="example.com", path="/app")
        cookie = resp.headers.get("set-cookie", "")
        assert "Domain=example.com" in cookie
        assert "Path=/app" in cookie


class TestHighConcurrency:
    """Stress-test the framework with many concurrent requests."""

    @pytest.mark.asyncio
    async def test_100_concurrent_requests_all_succeed(self) -> None:
        app = OpenViper()

        @app.get("/echo/{n:int}")
        async def echo(n: int) -> dict[str, int]:
            return {"n": n}

        async def single_request(n: int) -> int:
            scope = make_http_scope("GET", f"/echo/{n}")
            msgs = await run_app(app, scope)
            return extract_status(msgs)

        results = await asyncio.gather(*[single_request(i) for i in range(100)])
        assert all(r == 200 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_unique_path_params(self) -> None:
        app = OpenViper()

        @app.get("/users/{user_id:int}/profile")
        async def profile(user_id: int) -> dict[str, int]:
            return {"user": user_id}

        async def fetch_profile(uid: int) -> bytes:
            scope = make_http_scope("GET", f"/users/{uid}/profile")
            msgs = await run_app(app, scope)
            return extract_body(msgs)

        results = await asyncio.gather(*[fetch_profile(i) for i in range(50)])
        for i, body in enumerate(results):
            assert f'"user":{i}'.encode() in body

    @pytest.mark.asyncio
    async def test_concurrent_streaming_responses(self) -> None:
        app = OpenViper()

        @app.get("/stream/{id:int}")
        async def stream_handler(id: int) -> StreamingResponse:
            async def gen() -> t.AsyncIterator[bytes]:
                for chunk_id in range(5):
                    yield f"{id}:{chunk_id}".encode()

            return StreamingResponse(gen(), media_type="text/plain")

        async def fetch_stream(sid: int) -> int:
            scope = make_http_scope("GET", f"/stream/{sid}")
            msgs = await run_app(app, scope)
            return extract_status(msgs)

        results = await asyncio.gather(*[fetch_stream(i) for i in range(30)])
        assert all(r == 200 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_request_state_isolation_under_load(self) -> None:
        app = OpenViper()

        @app.get("/isolate/{value}")
        async def isolate(request: Request) -> dict[str, object]:
            request.state["v"] = request.path_params.get("value")
            await asyncio.sleep(0.001)
            return {"v": request.state.get("v")}

        async def check(val: str) -> bytes:
            scope = make_http_scope("GET", f"/isolate/{val}")
            msgs = await run_app(app, scope)
            return extract_body(msgs)

        values = [f"val{i}" for i in range(50)]
        results = await asyncio.gather(*[check(v) for v in values])
        for val, body in zip(values, results, strict=True):
            assert val.encode() in body

    @pytest.mark.asyncio
    async def test_mixed_methods_concurrent(self) -> None:
        app = OpenViper()
        store: dict[str, str] = {}

        @app.get("/item/{key}")
        async def get_item(key: str) -> dict[str, str]:
            return {"value": store.get(key, "")}

        @app.post("/item/{key}")
        async def set_item(key: str, request: Request) -> dict[str, str]:
            data = await request.json()
            store[key] = data.get("value", "")
            return {"ok": True}

        @app.delete("/item/{key}")
        async def del_item(key: str) -> dict[str, str]:
            store.pop(key, None)
            return {"deleted": True}

        async def do_get(k: str) -> int:
            scope = make_http_scope("GET", f"/item/{k}")
            msgs = await run_app(app, scope)
            return extract_status(msgs)

        async def do_post(k: str, body: bytes) -> int:
            scope = make_http_scope(
                "POST", f"/item/{k}",
                headers=[(b"content-type", b"application/json")],
            )
            msgs = await run_app(app, scope, body)
            return extract_status(msgs)

        post_tasks = [do_post(f"k{i}", b'{"value":"v"}') for i in range(20)]
        get_tasks = [do_get(f"k{i}") for i in range(20)]
        results = await asyncio.gather(*post_tasks, *get_tasks)
        assert all(r in (200, 201) for r in results[:20])
        assert all(r == 200 for r in results[20:])


class TestLargePayloads:
    """Test handling of large request/response bodies."""

    @pytest.mark.asyncio
    async def test_large_json_response_serialized_correctly(self) -> None:
        app = OpenViper()
        large_list = list(range(10000))

        @app.get("/large")
        async def handler() -> dict[str, list[int]]:
            return {"data": large_list}

        scope = make_http_scope("GET", "/large")
        msgs = await run_app(app, scope)
        body = extract_body(msgs)
        assert b"9999" in body
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_large_post_body_accepted(self) -> None:
        app = OpenViper()
        large_data = {"items": [{"id": i, "name": f"item{i}"} for i in range(100)]}
        body = json.dumps(large_data).encode()

        @app.post("/bulk")
        async def handler(request: Request) -> dict[str, int]:
            data = await request.json()
            return {"count": len(data.get("items", []))}

        scope = make_http_scope("POST", "/bulk", headers=[(b"content-type", b"application/json")])
        msgs = await run_app(app, scope, body)
        assert extract_status(msgs) == 200
        assert b'"count":100' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_body_exceeding_max_size_rejected(self) -> None:
        app = OpenViper()

        @app.post("/upload")
        async def handler(request: Request) -> dict[str, int]:
            await request.body()
            return {"ok": 1}

        oversized_body = b"x" * (MAX_BODY_SIZE + 1)
        scope = make_http_scope(
            "POST", "/upload",
            headers=[(b"content-length", str(len(oversized_body)).encode())],
        )

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": oversized_body, "more_body": False}

        msgs: list[dict[str, object]] = []

        async def send(msg: dict[str, object]) -> None:
            msgs.append(msg)

        await app(scope, receive, send)
        status = extract_status(msgs)
        assert status in (400, 500)

    @pytest.mark.asyncio
    async def test_streaming_large_response_in_chunks(self) -> None:
        app = OpenViper()
        total_chunks = 500
        chunk_size = 1024

        @app.get("/big-stream")
        async def handler() -> StreamingResponse:
            async def gen() -> t.AsyncIterator[bytes]:
                for _ in range(total_chunks):
                    yield b"x" * chunk_size

            return StreamingResponse(gen(), media_type="application/octet-stream")

        scope = make_http_scope("GET", "/big-stream")
        msgs = await run_app(app, scope)
        body = extract_body(msgs)
        assert len(body) == total_chunks * chunk_size


class TestEdgeCaseInputs:
    """Probe handlers with unusual but valid inputs."""

    @pytest.mark.asyncio
    async def test_empty_path_segments(self) -> None:
        app = OpenViper()

        @app.get("/api/v1/users")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        scope = make_http_scope("GET", "/api/v1/users")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_query_string_with_special_chars(self) -> None:
        app = OpenViper()

        @app.get("/search")
        async def handler(request: Request) -> dict[str, str]:
            q = request.query_params.get("q", "")
            return {"q": q}

        scope = make_http_scope("GET", "/search", query_string=b"q=hello+world&sort=desc")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_unicode_in_path(self) -> None:
        app = OpenViper()

        @app.get("/items/{name:str}")
        async def handler(name: str) -> dict[str, str]:
            return {"name": name}

        scope = make_http_scope("GET", "/items/caf%C3%A9")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_very_long_path(self) -> None:
        app = OpenViper()

        @app.get("/short")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        long_path = "/" + "a" * 8000
        scope = make_http_scope("GET", long_path)
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 404

    @pytest.mark.asyncio
    async def test_many_query_parameters(self) -> None:
        app = OpenViper()

        @app.get("/multi")
        async def handler(request: Request) -> dict[str, int]:
            return {"count": len(request.query_params)}

        qs = "&".join(f"p{i}=v{i}" for i in range(100))
        scope = make_http_scope("GET", "/multi", query_string=qs.encode())
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200

    @pytest.mark.asyncio
    async def test_deeply_nested_sub_routers(self) -> None:
        inner = Router()

        @inner.get("/leaf")
        async def leaf() -> dict[str, str]:
            return {"depth": "max"}

        level3 = Router(prefix="/level3")
        level3.include_router(inner)
        level2 = Router(prefix="/level2")
        level2.include_router(level3)
        level1 = Router(prefix="/level1")
        level1.include_router(level2)
        level0 = Router(prefix="/level0")
        level0.include_router(level1)

        app = OpenViper()
        app.include_router(level0, prefix="/root")

        scope = make_http_scope("GET", "/root/level0/level1/level2/level3/leaf")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert b'"max"' in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_handler_returning_pydantic_model(self) -> None:
        class Item(BaseModel):
            id: int
            name: str

        app = OpenViper()

        @app.get("/item")
        async def handler() -> Item:
            return Item(id=1, name="widget")

        scope = make_http_scope("GET", "/item")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        body = extract_body(msgs)
        assert b'"id":1' in body
        assert b'"name":"widget"' in body

    @pytest.mark.asyncio
    async def test_handler_returning_empty_string(self) -> None:
        app = OpenViper()

        @app.get("/empty")
        async def handler() -> str:
            return ""

        scope = make_http_scope("GET", "/empty")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 200
        assert extract_body(msgs) == b""

    @pytest.mark.asyncio
    async def test_handler_raising_http_exception_with_detail_dict(self) -> None:
        app = OpenViper()

        @app.get("/err")
        async def handler() -> t.NoReturn:
            raise HTTPException(422, {"code": "VALIDATION_ERROR", "fields": ["name"]})

        scope = make_http_scope("GET", "/err")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 422
        assert b"VALIDATION_ERROR" in extract_body(msgs)

    @pytest.mark.asyncio
    async def test_int_converter_rejects_non_numeric(self) -> None:
        app = OpenViper()

        @app.get("/users/{user_id:int}")
        async def handler(user_id: int) -> dict[str, int]:
            return {"id": user_id}

        scope = make_http_scope("GET", "/users/abc")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 404

    @pytest.mark.asyncio
    async def test_int_converter_rejects_overflow(self) -> None:
        app = OpenViper()

        @app.get("/users/{user_id:int}")
        async def handler(user_id: int) -> dict[str, int]:
            return {"id": user_id}

        scope = make_http_scope("GET", "/users/99999999999999999999")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) == 404

    def test_all_converters_registered(self) -> None:
        expected = {"str", "int", "float", "path", "uuid", "slug"}
        assert set(CONVERTERS.keys()) == expected


class TestRouterIntegrity:
    """Verify router caching and invalidation under dynamic route changes."""

    def test_cache_invalidated_on_new_route(self) -> None:
        router = Router()

        @router.get("/a")
        async def a() -> dict[str, str]:
            return {"a": "1"}

        first_count = len(router.routes)
        assert router.cached_routes is not None

        @router.get("/b")
        async def b() -> dict[str, str]:
            return {"b": "1"}

        assert router.cached_routes is None
        second_count = len(router.routes)
        assert second_count == first_count + 1

    def test_cache_invalidated_on_sub_router_addition(self) -> None:
        router = Router()

        @router.get("/a")
        async def a() -> dict[str, str]:
            return {"a": "1"}

        assert len(router.routes) == 1
        assert router.cached_routes is not None

        sub = Router()

        @sub.get("/sub")
        async def sub_handler() -> dict[str, str]:
            return {"sub": "1"}

        router.include_router(sub, prefix="/api")
        assert router.cached_routes is None
        assert len(router.routes) == 2

    def test_invalidation_propagates_to_parents(self) -> None:
        parent = Router()
        child = Router()

        @child.get("/child")
        async def child_handler() -> dict[str, str]:
            return {"child": "1"}

        parent.include_router(child, prefix="/api")
        assert len(parent.routes) >= 1
        assert parent.cached_routes is not None

        @child.get("/new")
        async def new_handler() -> dict[str, str]:
            return {"new": "1"}

        assert child.cached_routes is None
        assert parent.cached_routes is None

    def test_name_index_built_correctly(self) -> None:
        router = Router()

        @router.get("/a", name="route_a")
        async def a() -> dict[str, str]:
            return {"a": "1"}

        @router.get("/b", name="route_b")
        async def b() -> dict[str, str]:
            return {"b": "1"}

        assert len(router.routes) == 2
        assert "route_a" in router.name_index
        assert "route_b" in router.name_index

    def test_exact_index_groups_multi_method_routes(self) -> None:
        router = Router()

        @router.get("/shared")
        async def get_shared() -> dict[str, str]:
            return {"method": "GET"}

        @router.post("/shared")
        async def post_shared(request: Request) -> dict[str, str]:
            return {"method": "POST"}

        assert len(router.routes) == 2
        exact = router.exact_index
        assert "/shared" in exact
        assert len(exact["/shared"]) == 2

    def test_resolve_tries_slash_variants(self) -> None:
        router = Router()

        @router.get("/items/")
        async def list_items() -> dict[str, str]:
            return {"items": "all"}

        route, params = router.resolve("GET", "/items")
        assert route.path == "/items/"

        route2, params2 = router.resolve("GET", "/items/")
        assert route2.path == "/items/"


class TestFileResponseEdgeCases:
    """Probe FileResponse with edge-case file scenarios."""

    def make_temp_file(self, content: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".bin")
        os.write(fd, content)
        os.close(fd)
        return path

    @pytest.mark.asyncio
    async def test_empty_file_served(self) -> None:
        path = self.make_temp_file(b"")
        try:
            app = OpenViper()

            @app.get("/empty")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="application/octet-stream")

            scope = make_http_scope("GET", "/empty")
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 200
            assert extract_body(msgs) == b""
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_single_byte_file(self) -> None:
        path = self.make_temp_file(b"X")
        try:
            app = OpenViper()

            @app.get("/one")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="application/octet-stream")

            scope = make_http_scope("GET", "/one")
            msgs = await run_app(app, scope)
            assert extract_body(msgs) == b"X"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_range_start_equals_end(self) -> None:
        content = b"0123456789"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/f")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/f", headers=[(b"range", b"bytes=5-5")])
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 206
            assert extract_body(msgs) == b"5"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_open_ended_range(self) -> None:
        content = b"0123456789ABCDEF"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/f")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/f", headers=[(b"range", b"bytes=10-")])
            msgs = await run_app(app, scope)
            assert extract_status(msgs) == 206
            assert extract_body(msgs) == content[10:]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_if_modified_since_returns_304(self) -> None:
        content = b"modified content"
        path = self.make_temp_file(content)
        try:
            app = OpenViper()

            @app.get("/f")
            async def handler() -> FileResponse:
                return FileResponse(path, media_type="text/plain")

            scope = make_http_scope("GET", "/f")
            msgs = await run_app(app, scope)
            headers = extract_headers(msgs)
            last_modified = headers.get(b"last-modified", b"")

            scope2 = make_http_scope("GET", "/f", headers=[(b"if-modified-since", last_modified)])
            msgs2 = await run_app(app, scope2)
            assert extract_status(msgs2) == 304
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_filename_sanitized_in_content_disposition(self) -> None:
        path = self.make_temp_file(b"content")
        try:
            app = OpenViper()

            @app.get("/dl")
            async def handler() -> FileResponse:
                return FileResponse(
                    path, media_type="text/plain", filename='evil\r\n" injection.txt'
                )

            scope = make_http_scope("GET", "/dl")
            msgs = await run_app(app, scope)
            headers = extract_headers(msgs)
            cd = headers.get(b"content-disposition", b"")
            assert b"\r" not in cd
            assert b"\n" not in cd
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises_on_call(self) -> None:
        app = OpenViper()

        @app.get("/missing")
        async def handler() -> FileResponse:
            return FileResponse("/nonexistent/file/path.txt")

        scope = make_http_scope("GET", "/missing")
        msgs = await run_app(app, scope)
        assert extract_status(msgs) in (404, 500)
