"""Unit tests for openviper.http.request."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

import openviper.http.request as _req_mod
from openviper.http.request import URL, Request, UploadFile
from openviper.utils.datastructures import Headers, ImmutableMultiDict, QueryParams

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scope(
    method="GET",
    path="/",
    query_string=b"",
    headers=None,
    scheme="http",
    server=("localhost", 8000),
):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "headers": headers or [],
        "scheme": scheme,
        "server": server,
        "root_path": "",
    }


def make_receive(body=b"", more=False):
    async def _receive():
        return {"type": "http.request", "body": body, "more_body": more}

    return _receive


def make_chunked_receive(chunks):
    """Simulate a multi-chunk body stream."""
    _chunks = list(chunks)

    async def _receive():
        if _chunks:
            chunk = _chunks.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(_chunks)}
        return {"type": "http.request", "body": b"", "more_body": False}

    return _receive


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------


class TestURL:
    def test_scheme(self):
        url = URL(make_scope(scheme="https"))
        assert url.scheme == "https"

    def test_path(self):
        url = URL(make_scope(path="/api/v1"))
        assert url.path == "/api/v1"

    def test_query_string(self):
        url = URL(make_scope(query_string=b"a=1&b=2"))
        assert url.query_string == "a=1&b=2"

    def test_host_from_server_standard_port(self):
        url = URL(make_scope(scheme="http", server=("example.com", 80)))
        assert url.host == "example.com"

    def test_host_from_server_https_standard_port(self):
        url = URL(make_scope(scheme="https", server=("example.com", 443)))
        assert url.host == "example.com"

    def test_host_from_server_non_standard_port(self):
        url = URL(make_scope(scheme="http", server=("example.com", 8080)))
        assert url.host == "example.com:8080"

    def test_host_from_host_header_when_no_server(self):
        scope = make_scope()
        scope["server"] = None
        scope["headers"] = [(b"host", b"myapp.io")]
        url = URL(scope)
        assert url.host == "myapp.io"

    def test_host_defaults_to_localhost_when_no_server_no_header(self):
        scope = make_scope()
        scope["server"] = None
        url = URL(scope)
        assert url.host == "localhost"

    def test_host_from_header_rejects_crlf_injection(self):
        # A Host header containing CRLF must be rejected → falls back to localhost.
        scope = make_scope()
        scope["server"] = None
        scope["headers"] = [(b"host", b"evil.com\r\nX-Injected: pwned")]
        url = URL(scope)
        assert url.host == "localhost"

    def test_host_from_header_rejects_spaces(self):
        scope = make_scope()
        scope["server"] = None
        scope["headers"] = [(b"host", b"not a valid host")]
        url = URL(scope)
        assert url.host == "localhost"

    def test_str_no_query(self):
        url = URL(make_scope(path="/test"))
        assert str(url) == "http://localhost:8000/test"

    def test_str_with_query(self):
        url = URL(make_scope(path="/search", query_string=b"q=python"))
        assert "q=python" in str(url)

    def test_str_cached(self):
        url = URL(make_scope(path="/"))
        s1 = str(url)
        s2 = str(url)
        assert s1 is s2  # same cached object

    def test_repr(self):
        url = URL(make_scope(path="/"))
        assert "URL" in repr(url)


# ---------------------------------------------------------------------------
# Request — basic properties
# ---------------------------------------------------------------------------


class TestRequestProperties:
    def test_method(self):
        req = Request(make_scope(method="POST"))
        assert req.method == "POST"

    def test_method_normalized_uppercase(self):
        req = Request(make_scope(method="get"))
        assert req.method == "GET"

    def test_path(self):
        req = Request(make_scope(path="/users/1"))
        assert req.path == "/users/1"

    def test_root_path(self):
        scope = make_scope()
        scope["root_path"] = "/api"
        req = Request(scope)
        assert req.root_path == "/api"

    def test_headers_returns_headers_instance(self):
        req = Request(make_scope())
        assert isinstance(req.headers, Headers)

    def test_query_params_returns_query_params_instance(self):
        req = Request(make_scope(query_string=b"a=1"))
        assert isinstance(req.query_params, QueryParams)
        assert req.query_params.get("a") == "1"

    def test_client(self):
        scope = make_scope()
        scope["client"] = ("127.0.0.1", 54321)
        req = Request(scope)
        assert req.client == ("127.0.0.1", 54321)

    def test_client_none_when_absent(self):
        scope = make_scope()
        scope.pop("client", None)
        req = Request(scope)
        assert req.client is None

    def test_url_returns_url_instance(self):
        req = Request(make_scope())
        assert isinstance(req.url, URL)

    def test_url_property_is_cached(self):
        req = Request(make_scope())
        assert req.url is req.url

    def test_is_secure_http(self):
        req = Request(make_scope(scheme="http"))
        assert req.is_secure() is False

    def test_is_secure_https(self):
        req = Request(make_scope(scheme="https"))
        assert req.is_secure() is True

    def test_is_secure_wss(self):
        req = Request(make_scope(scheme="wss"))
        assert req.is_secure() is True

    def test_state_is_empty_dict_by_default(self):
        req = Request(make_scope())
        assert req.state == {}

    def test_user_and_auth_default_none(self):
        req = Request(make_scope())
        assert req.user is None
        assert req.auth is None

    def test_path_params_from_scope(self):
        scope = make_scope()
        scope["path_params"] = {"id": 42}
        req = Request(scope)
        assert req.path_params["id"] == 42

    def test_wrong_scope_type_raises(self):
        scope = {"type": "websocket"}
        with pytest.raises(TypeError, match="HTTP scope"):
            Request(scope)

    def test_repr(self):
        req = Request(make_scope(method="GET", path="/api"))
        r = repr(req)
        assert "GET" in r
        assert "/api" in r


# ---------------------------------------------------------------------------
# Request — header raw lookup
# ---------------------------------------------------------------------------


class TestRequestHeaderRawLookup:
    def test_header_returns_bytes(self):
        scope = make_scope(headers=[(b"content-type", b"application/json")])
        req = Request(scope)
        assert req.header(b"content-type") == b"application/json"

    def test_header_returns_none_for_missing(self):
        req = Request(make_scope())
        assert req.header(b"x-missing") is None

    def test_header_cache_is_built_lazily(self):
        req = Request(make_scope(headers=[(b"x-test", b"val")]))
        assert req._headers_map is None
        req.header(b"x-test")
        assert req._headers_map is not None


# ---------------------------------------------------------------------------
# Request — cookies
# ---------------------------------------------------------------------------


class TestRequestCookies:
    def test_parses_single_cookie(self):
        scope = make_scope(headers=[(b"cookie", b"session=abc123")])
        req = Request(scope)
        assert req.cookies.get("session") == "abc123"

    def test_parses_multiple_cookies(self):
        scope = make_scope(headers=[(b"cookie", b"a=1; b=2")])
        req = Request(scope)
        assert req.cookies["a"] == "1"
        assert req.cookies["b"] == "2"

    def test_no_cookie_header_returns_empty_dict(self):
        req = Request(make_scope())
        assert req.cookies == {}

    def test_cookies_cached(self):
        scope = make_scope(headers=[(b"cookie", b"x=1")])
        req = Request(scope)
        c1 = req.cookies
        c2 = req.cookies
        assert c1 is c2


# ---------------------------------------------------------------------------
# Request — body reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRequestBody:
    async def test_body_simple(self):
        req = Request(make_scope(), receive=make_receive(b"hello"))
        body = await req.body()
        assert body == b"hello"

    async def test_body_cached(self):
        req = Request(make_scope(), receive=make_receive(b"data"))
        b1 = await req.body()
        b2 = await req.body()
        assert b1 is b2

    async def test_body_chunked(self):
        receive = make_chunked_receive([b"hel", b"lo"])
        req = Request(make_scope(), receive=receive)
        body = await req.body()
        assert body == b"hello"

    async def test_body_empty(self):
        req = Request(make_scope(), receive=make_receive(b""))
        assert await req.body() == b""

    async def test_body_with_content_length_hint(self):
        headers = [(b"content-length", b"5")]
        scope = make_scope(headers=headers)
        req = Request(scope, receive=make_receive(b"hello"))
        body = await req.body()
        assert body == b"hello"

    async def test_json_parsing(self):
        payload = json.dumps({"key": "value"}).encode()
        req = Request(
            make_scope(headers=[(b"content-type", b"application/json")]),
            receive=make_receive(payload),
        )
        data = await req.json()
        assert data == {"key": "value"}

    async def test_json_cached(self):
        payload = json.dumps({"x": 1}).encode()
        req = Request(make_scope(), receive=make_receive(payload))
        j1 = await req.json()
        j2 = await req.json()
        assert j1 is j2

    async def test_form_urlencoded(self):
        body = b"name=Alice&age=30"
        headers = [(b"content-type", b"application/x-www-form-urlencoded")]
        req = Request(make_scope(headers=headers), receive=make_receive(body))
        form = await req.form()
        assert isinstance(form, ImmutableMultiDict)
        assert form["name"] == "Alice"

    async def test_form_non_urlencoded_returns_empty(self):
        headers = [(b"content-type", b"multipart/form-data")]
        req = Request(make_scope(headers=headers), receive=make_receive(b"data"))
        form = await req.form()
        assert len(form) == 0

    async def test_stream_yields_body(self):
        req = Request(make_scope(), receive=make_receive(b"streaming"))
        chunks = []
        async for chunk in req.stream():
            chunks.append(chunk)
        assert b"".join(chunks) == b"streaming"

    async def test_stream_yields_cached_body(self):
        req = Request(make_scope(), receive=make_receive(b"cached"))
        _ = await req.body()  # populate cache
        chunks = []
        async for chunk in req.stream():
            chunks.append(chunk)
        assert b"".join(chunks) == b"cached"

    async def test_stream_caches_body_for_subsequent_body_call(self):
        # stream() must set _body so body() works without re-calling receive.
        req = Request(make_scope(), receive=make_receive(b"streamed"))
        chunks = []
        async for chunk in req.stream():
            chunks.append(chunk)
        assert b"".join(chunks) == b"streamed"
        body = await req.body()
        assert body == b"streamed"

    async def test_body_rejects_oversized_content_length(self):
        # Patch MAX_BODY_SIZE so the test doesn't need to allocate 10 MB.
        with patch.object(_req_mod, "MAX_BODY_SIZE", 10):
            headers = [(b"content-length", b"100")]
            req = Request(make_scope(headers=headers), receive=make_receive(b"x"))
            with pytest.raises(ValueError, match="too large"):
                await req.body()

    async def test_body_rejects_body_exceeding_declared_content_length(self):
        # Actual body (5 bytes) exceeds declared Content-Length (3).
        headers = [(b"content-length", b"3")]
        req = Request(make_scope(headers=headers), receive=make_receive(b"hello"))
        with pytest.raises(ValueError, match="exceeds"):
            await req.body()

    async def test_body_rejects_oversized_body_without_content_length(self):
        with patch.object(_req_mod, "MAX_BODY_SIZE", 4):
            req = Request(make_scope(), receive=make_receive(b"toolong"))
            with pytest.raises(ValueError, match="maximum allowed size"):
                await req.body()

    async def test_stream_rejects_oversized_body(self):
        with patch.object(_req_mod, "MAX_BODY_SIZE", 4):
            req = Request(make_scope(), receive=make_receive(b"toolong"))
            with pytest.raises(ValueError, match="maximum allowed size"):
                async for _ in req.stream():
                    pass


# ---------------------------------------------------------------------------
# UploadFile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUploadFile:
    async def test_read(self):

        f = io.BytesIO(b"file content")
        upload = UploadFile("test.txt", "text/plain", f)
        data = await upload.read()
        assert data == b"file content"

    async def test_seek(self):

        f = io.BytesIO(b"0123456789")
        upload = UploadFile("file.bin", "application/octet-stream", f)
        await upload.read()  # read to end
        await upload.seek(0)
        data = await upload.read()
        assert data == b"0123456789"

    async def test_close(self):

        f = io.BytesIO(b"data")
        upload = UploadFile("f.txt", "text/plain", f)
        await upload.close()
        assert f.closed

    def test_repr(self):

        f = io.BytesIO(b"")
        upload = UploadFile("photo.jpg", "image/jpeg", f)
        r = repr(upload)
        assert "photo.jpg" in r
        assert "image/jpeg" in r


# ── form() else-branch for non-form content-type (line 285) ────────────────


class TestFormElseBranch:
    @pytest.mark.asyncio
    async def test_form_returns_empty_for_json_content_type(self):
        """form() sets _form to ImmutableMultiDict([]) for non-form content-type (line 285)."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b'{"key":"val"}', "more_body": False}

        req = Request(scope, receive)
        form = await req.form()
        assert isinstance(form, ImmutableMultiDict)
        assert list(form.multi_items()) == []
