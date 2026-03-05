"""Integration tests for openviper HTTP response classes."""

from __future__ import annotations

import datetime
import gzip
import json
import os
import tempfile
import uuid

import pytest

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _call_response(response):
    """Call response ASGI callable, collect scope messages."""
    messages = []

    async def send(msg):
        messages.append(msg)

    scope = {"type": "http", "method": "GET", "path": "/"}
    await response(scope, None, send)
    return messages


# ---------------------------------------------------------------------------
# Base Response
# ---------------------------------------------------------------------------


class TestResponse:
    def test_default_status_200(self):
        r = Response("hello")
        assert r.status_code == 200

    def test_custom_status_code(self):
        r = Response("not found", status_code=404)
        assert r.status_code == 404

    def test_body_is_bytes(self):
        r = Response("hello")
        assert isinstance(r.body, bytes)
        assert b"hello" in r.body

    def test_str_body_encoded_to_bytes(self):
        r = Response("hello world")
        assert r.body == b"hello world"

    def test_bytes_body_unchanged(self):
        r = Response(b"raw bytes")
        assert r.body == b"raw bytes"

    def test_none_body_is_empty(self):
        r = Response(None)
        assert r.body == b""

    def test_custom_headers(self):
        r = Response("ok", headers={"X-Custom": "value"})
        header_keys = [h[0] for h in r.headers.raw]
        assert b"x-custom" in header_keys

    @pytest.mark.asyncio
    async def test_asgi_call_sends_messages(self):
        r = Response("hello", status_code=200)
        messages = await _call_response(r)
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 200
        assert messages[1]["type"] == "http.response.body"
        assert b"hello" in messages[1]["body"]

    def test_set_cookie_basic(self):
        r = Response("ok")
        r.set_cookie("session", "abc123")
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        assert any("session=abc123" in v for v in header_values)

    def test_set_cookie_with_max_age(self):
        r = Response("ok")
        r.set_cookie("token", "xyz", max_age=3600)
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        assert any("Max-Age=3600" in v for v in header_values)

    def test_set_cookie_with_domain(self):
        r = Response("ok")
        r.set_cookie("id", "1", domain="example.com")
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        assert any("Domain=example.com" in v for v in header_values)

    def test_set_cookie_secure_httponly(self):
        r = Response("ok")
        r.set_cookie("secure_token", "val", secure=True, httponly=True)
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        cookie_str = header_values[0]
        assert "Secure" in cookie_str
        assert "HttpOnly" in cookie_str

    def test_set_cookie_samesite_strict(self):
        r = Response("ok")
        r.set_cookie("k", "v", samesite="strict")
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        assert any("SameSite=Strict" in v for v in header_values)

    def test_delete_cookie(self):
        r = Response("ok")
        r.delete_cookie("session")
        header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"set-cookie"]
        assert any("Max-Age=0" in v for v in header_values)


# ---------------------------------------------------------------------------
# JSONResponse
# ---------------------------------------------------------------------------


class TestJSONResponse:
    def test_json_content_type(self):
        r = JSONResponse({"key": "value"})
        content_type_headers = [h for h in r.headers.raw if h[0] == b"content-type"]
        assert any(b"application/json" in h[1] for h in content_type_headers)

    def test_json_body_is_valid_json(self):
        r = JSONResponse({"name": "Alice", "age": 30})
        data = json.loads(r.body)
        assert data["name"] == "Alice"
        assert data["age"] == 30

    def test_json_with_datetime(self):
        r = JSONResponse({"created": datetime.datetime(2023, 1, 15, 10, 30, 0)})
        data = json.loads(r.body)
        assert "2023-01-15" in data["created"]

    def test_json_with_date(self):
        r = JSONResponse({"date": datetime.date(2023, 5, 20)})
        data = json.loads(r.body)
        assert "2023-05-20" in data["date"]

    def test_json_with_uuid(self):
        uid = uuid.uuid4()
        r = JSONResponse({"uid": uid})
        data = json.loads(r.body)
        assert data["uid"] == str(uid)

    def test_json_unserializable_raises_type_error(self):
        class Unserializable:
            pass

        with pytest.raises(TypeError, match="not JSON serializable"):
            JSONResponse({"obj": Unserializable()})

    def test_json_indent(self):
        r = JSONResponse({"x": 1}, indent=2)
        body_str = r.body.decode()
        assert "\n" in body_str  # Indented JSON has newlines

    def test_json_null_content(self):
        r = JSONResponse(None)
        data = json.loads(r.body)
        assert data is None

    def test_json_list_content(self):
        r = JSONResponse([1, 2, 3])
        data = json.loads(r.body)
        assert data == [1, 2, 3]


# ---------------------------------------------------------------------------
# PlainTextResponse
# ---------------------------------------------------------------------------


class TestPlainTextResponse:
    def test_plain_text_media_type(self):
        r = PlainTextResponse("hello")
        content_type_headers = [h for h in r.headers.raw if h[0] == b"content-type"]
        assert any(b"text/plain" in h[1] for h in content_type_headers)

    def test_plain_text_body(self):
        r = PlainTextResponse("plain text")
        assert b"plain text" in r.body


# ---------------------------------------------------------------------------
# HTMLResponse
# ---------------------------------------------------------------------------


class TestHTMLResponse:
    def test_html_direct_content(self):
        r = HTMLResponse("<h1>Hello</h1>")
        assert b"<h1>Hello</h1>" in r.body

    def test_html_media_type(self):
        r = HTMLResponse("<p>test</p>")
        content_type_headers = [h for h in r.headers.raw if h[0] == b"content-type"]
        assert any(b"text/html" in h[1] for h in content_type_headers)

    def test_html_cannot_have_both_content_and_template(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            HTMLResponse(content="<p>stuff</p>", template="index.html")

    def test_html_none_content(self):
        r = HTMLResponse(None)
        assert r.body == b""


# ---------------------------------------------------------------------------
# RedirectResponse
# ---------------------------------------------------------------------------


class TestRedirectResponse:
    def test_redirect_default_307(self):
        r = RedirectResponse("/new-path")
        assert r.status_code == 307

    def test_redirect_custom_status(self):
        r = RedirectResponse("/old", status_code=301)
        assert r.status_code == 301

    def test_redirect_location_header(self):
        r = RedirectResponse("/target")
        location_headers = [h for h in r.headers.raw if h[0] == b"location"]
        assert any(b"/target" in h[1] for h in location_headers)

    @pytest.mark.asyncio
    async def test_redirect_asgi_call(self):
        r = RedirectResponse("/somewhere", status_code=302)
        messages = await _call_response(r)
        assert messages[0]["status"] == 302


# ---------------------------------------------------------------------------
# StreamingResponse
# ---------------------------------------------------------------------------


class TestStreamingResponse:
    @pytest.mark.asyncio
    async def test_async_generator(self):
        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        r = StreamingResponse(gen())
        messages = await _call_response(r)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        bodies = b"".join(m["body"] for m in body_messages)
        assert b"chunk1" in bodies
        assert b"chunk2" in bodies

    @pytest.mark.asyncio
    async def test_sync_iterator(self):
        r = StreamingResponse(iter([b"hello", b" world"]))
        messages = await _call_response(r)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        bodies = b"".join(m["body"] for m in body_messages)
        assert b"hello" in bodies
        assert b"world" in bodies

    @pytest.mark.asyncio
    async def test_callable_async_generator(self):
        def make_gen():
            async def gen():
                yield b"from callable"

            return gen()

        r = StreamingResponse(make_gen)
        messages = await _call_response(r)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        bodies = b"".join(m["body"] for m in body_messages)
        assert b"from callable" in bodies

    def test_streaming_status_code(self):
        r = StreamingResponse(iter([b"ok"]), status_code=206)
        assert r.status_code == 206

    def test_streaming_custom_media_type(self):
        r = StreamingResponse(iter([]), media_type="text/event-stream")
        assert r.media_type == "text/event-stream"


# ---------------------------------------------------------------------------
# FileResponse
# ---------------------------------------------------------------------------


class TestFileResponse:
    @pytest.mark.asyncio
    async def test_file_response_serves_content(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"file content here")
            tmp_path = f.name

        try:
            r = FileResponse(tmp_path)
            messages = await _call_response(r)
            body_messages = [m for m in messages if m["type"] == "http.response.body"]
            bodies = b"".join(m["body"] for m in body_messages)
            assert b"file content here" in bodies
        finally:
            os.unlink(tmp_path)

    def test_file_response_guesses_media_type(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"{}")
            tmp_path = f.name
        try:
            r = FileResponse(tmp_path)
            assert "json" in r.media_type or "octet" in r.media_type
        finally:
            os.unlink(tmp_path)

    def test_file_response_with_filename_header(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"data")
            tmp_path = f.name
        try:
            r = FileResponse(tmp_path, filename="download.txt")
            header_values = [h[1].decode() for h in r.headers.raw if h[0] == b"content-disposition"]
            assert any("download.txt" in v for v in header_values)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# GZipResponse
# ---------------------------------------------------------------------------


class TestGZipResponse:
    @pytest.mark.asyncio
    async def test_compresses_large_body(self):
        # Body larger than minimum_size (500)
        large_body = b"x" * 1000
        inner = Response(large_body)
        gz = GZipResponse(inner, minimum_size=500)

        messages = await _call_response(gz)
        messages[0]
        body_msg = messages[1]

        # Should be compressed
        compressed_body = body_msg["body"]
        assert len(compressed_body) < len(large_body)
        # Verify it's valid gzip
        decompressed = gzip.decompress(compressed_body)
        assert decompressed == large_body

    @pytest.mark.asyncio
    async def test_does_not_compress_small_body(self):
        # Body smaller than minimum_size
        small_body = b"small"
        inner = Response(small_body)
        gz = GZipResponse(inner, minimum_size=500)

        messages = await _call_response(gz)
        body_msg = messages[1]
        # Should not be compressed
        assert body_msg["body"] == small_body

    @pytest.mark.asyncio
    async def test_gzip_headers_set_on_compression(self):
        large_body = b"y" * 1000
        inner = Response(large_body)
        gz = GZipResponse(inner, minimum_size=100)

        messages = await _call_response(gz)
        start_msg = messages[0]
        headers = {h[0]: h[1] for h in start_msg["headers"]}
        assert b"content-encoding" in headers
        assert headers[b"content-encoding"] == b"gzip"
