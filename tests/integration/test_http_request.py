"""Integration tests for openviper.http.request (Request, URL, UploadFile)."""

from __future__ import annotations

import io

import pytest

from openviper.http.request import URL, Request, UploadFile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scope(
    method="GET",
    path="/",
    headers=None,
    query_string=b"",
    server=None,
    scheme="http",
):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
        "server": server,
        "scheme": scheme,
    }


async def make_receive(body=b""):
    """Return a simple receive callable that yields the body once."""

    async def receive():
        return {"body": body, "more_body": False}

    return receive


# ---------------------------------------------------------------------------
# UploadFile
# ---------------------------------------------------------------------------


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_read(self):
        buf = io.BytesIO(b"hello file")
        uf = UploadFile(filename="test.txt", content_type="text/plain", file=buf)
        data = await uf.read()
        assert data == b"hello file"

    @pytest.mark.asyncio
    async def test_seek(self):
        buf = io.BytesIO(b"seekable")
        uf = UploadFile(filename="f.bin", content_type="application/octet-stream", file=buf)
        await uf.read()
        await uf.seek(0)
        assert await uf.read() == b"seekable"

    @pytest.mark.asyncio
    async def test_close(self):
        buf = io.BytesIO(b"data")
        uf = UploadFile(filename="x.txt", content_type="text/plain", file=buf)
        await uf.close()

    def test_repr(self):
        buf = io.BytesIO(b"")
        uf = UploadFile(filename="file.txt", content_type="text/plain", file=buf)
        r = repr(uf)
        assert "file.txt" in r
        assert "text/plain" in r


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------


class TestURL:
    def test_scheme_default_http(self):
        scope = make_scope(scheme="http")
        url = URL(scope)
        assert url.scheme == "http"

    def test_scheme_https(self):
        scope = make_scope(scheme="https")
        url = URL(scope)
        assert url.scheme == "https"

    def test_path(self):
        scope = make_scope(path="/users/42")
        url = URL(scope)
        assert url.path == "/users/42"

    def test_query_string_present(self):
        scope = make_scope(query_string=b"page=2&limit=10")
        url = URL(scope)
        assert url.query_string == "page=2&limit=10"

    def test_query_string_absent(self):
        scope = make_scope()
        url = URL(scope)
        assert url.query_string == ""

    def test_host_from_server_standard_port(self):
        scope = make_scope(server=("example.com", 80))
        url = URL(scope)
        assert url.host == "example.com"

    def test_host_from_server_standard_https(self):
        scope = make_scope(server=("example.com", 443), scheme="https")
        url = URL(scope)
        assert url.host == "example.com"

    def test_host_from_server_nonstandard_port(self):
        scope = make_scope(server=("example.com", 8000))
        url = URL(scope)
        assert url.host == "example.com:8000"

    def test_host_from_header(self):
        scope = make_scope(headers=[(b"host", b"mysite.com")])
        url = URL(scope)
        assert url.host == "mysite.com"

    def test_host_fallback_localhost(self):
        scope = make_scope()
        url = URL(scope)
        assert url.host == "localhost"

    def test_str_no_query(self):
        scope = make_scope(scheme="http", path="/page", server=("example.com", 80))
        url = URL(scope)
        assert str(url) == "http://example.com/page"

    def test_str_with_query(self):
        scope = make_scope(path="/search", query_string=b"q=hello", server=("host", 80))
        url = URL(scope)
        s = str(url)
        assert "q=hello" in s

    def test_str_cached(self):
        scope = make_scope(server=("x.com", 80))
        url = URL(scope)
        first = str(url)
        second = str(url)
        assert first is second  # Same object (cached)

    def test_repr(self):
        scope = make_scope(server=("x.com", 80))
        url = URL(scope)
        r = repr(url)
        assert "URL(" in r


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class TestRequest:
    def test_method_upper(self):
        scope = make_scope(method="post")
        req = Request(scope)
        assert req.method == "POST"

    def test_path(self):
        scope = make_scope(path="/test/path")
        req = Request(scope)
        assert req.path == "/test/path"

    def test_root_path_default_empty(self):
        scope = make_scope()
        req = Request(scope)
        assert req.root_path == ""

    def test_root_path_from_scope(self):
        scope = make_scope()
        scope["root_path"] = "/app"
        req = Request(scope)
        assert req.root_path == "/app"

    def test_headers_lazy(self):
        scope = make_scope(headers=[(b"x-custom", b"hello")])
        req = Request(scope)
        assert req.headers["x-custom"] == "hello"

    def test_headers_cached(self):
        scope = make_scope(headers=[(b"x-h", b"v")])
        req = Request(scope)
        h1 = req.headers
        h2 = req.headers
        assert h1 is h2

    def test_query_params(self):
        scope = make_scope(query_string=b"foo=bar&baz=1")
        req = Request(scope)
        assert req.query_params["foo"] == "bar"
        assert req.query_params["baz"] == "1"

    def test_query_params_cached(self):
        scope = make_scope(query_string=b"a=1")
        req = Request(scope)
        qp1 = req.query_params
        qp2 = req.query_params
        assert qp1 is qp2

    def test_cookies_parsed(self):
        scope = make_scope(headers=[(b"cookie", b"session=abc; token=xyz")])
        req = Request(scope)
        assert req.cookies["session"] == "abc"
        assert req.cookies["token"] == "xyz"

    def test_cookies_empty(self):
        scope = make_scope()
        req = Request(scope)
        assert req.cookies == {}

    def test_cookies_cached(self):
        scope = make_scope(headers=[(b"cookie", b"a=1")])
        req = Request(scope)
        c1 = req.cookies
        c2 = req.cookies
        assert c1 is c2

    def test_client(self):
        scope = make_scope()
        scope["client"] = ("127.0.0.1", 1234)
        req = Request(scope)
        assert req.client == ("127.0.0.1", 1234)

    def test_client_none(self):
        scope = make_scope()
        req = Request(scope)
        assert req.client is None

    def test_is_secure_http(self):
        scope = make_scope(scheme="http")
        req = Request(scope)
        assert req.is_secure() is False

    def test_is_secure_https(self):
        scope = make_scope(scheme="https")
        req = Request(scope)
        assert req.is_secure() is True

    def test_url_property(self):
        scope = make_scope(path="/hello")
        req = Request(scope)
        assert req.url.path == "/hello"

    def test_repr(self):
        scope = make_scope(method="GET", path="/x", server=("host", 80))
        req = Request(scope)
        r = repr(req)
        assert "GET" in r

    def test_path_params_from_scope(self):
        scope = make_scope()
        scope["path_params"] = {"id": "42"}
        req = Request(scope)
        assert req.path_params["id"] == "42"

    def test_state_dict(self):
        scope = make_scope()
        req = Request(scope)
        req.state["key"] = "value"
        assert req.state["key"] == "value"

    def test_invalid_scope_type_raises(self):
        with pytest.raises(AssertionError):
            Request({"type": "websocket"})

    @pytest.mark.asyncio
    async def test_body_reads_once(self):
        scope = make_scope()
        receive = await make_receive(b"hello body")
        req = Request(scope, receive)
        body = await req.body()
        assert body == b"hello body"

    @pytest.mark.asyncio
    async def test_body_cached(self):
        scope = make_scope()
        call_count = 0

        async def receive():
            nonlocal call_count
            call_count += 1
            return {"body": b"data", "more_body": False}

        req = Request(scope, receive)
        await req.body()
        await req.body()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_json_parsing(self):
        scope = make_scope()
        body = b'{"key": "value", "num": 42}'
        receive = await make_receive(body)
        req = Request(scope, receive)
        data = await req.json()
        assert data["key"] == "value"
        assert data["num"] == 42

    @pytest.mark.asyncio
    async def test_form_urlencoded(self):
        scope = make_scope(headers=[(b"content-type", b"application/x-www-form-urlencoded")])
        body = b"name=Alice&age=30"
        receive = await make_receive(body)
        req = Request(scope, receive)
        form = await req.form()
        assert form.get("name") == "Alice"
        assert form.get("age") == "30"

    @pytest.mark.asyncio
    async def test_form_non_urlencoded_returns_empty(self):
        scope = make_scope(headers=[(b"content-type", b"application/json")])
        receive = await make_receive(b"{}")
        req = Request(scope, receive)
        form = await req.form()
        assert form.multi_items() == []

    @pytest.mark.asyncio
    async def test_stream_from_body(self):
        scope = make_scope()
        receive = await make_receive(b"stream data")
        req = Request(scope, receive)
        # Pre-load body
        await req.body()
        chunks = []
        async for chunk in req.stream():
            chunks.append(chunk)
        assert b"stream data" in b"".join(chunks)

    @pytest.mark.asyncio
    async def test_stream_directly(self):
        scope = make_scope()
        call_n = 0

        async def receive():
            nonlocal call_n
            call_n += 1
            if call_n == 1:
                return {"body": b"part1", "more_body": True}
            return {"body": b"part2", "more_body": False}

        req = Request(scope, receive)
        chunks = []
        async for chunk in req.stream():
            chunks.append(chunk)
        assert b"part1" in b"".join(chunks)
