"""Unit tests for openviper.http.response."""

from __future__ import annotations

import datetime
import email.utils
import gzip
import json
import os
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
    _json_encode,
)
from openviper.utils.datastructures import MutableHeaders

# ---------------------------------------------------------------------------
# _json_encode helper
# ---------------------------------------------------------------------------


class TestJsonEncode:
    def test_basic_dict(self):
        result = _json_encode({"a": 1}, default=None, indent=None)
        assert b'"a"' in result

    def test_indent_2(self):
        result = _json_encode({"a": 1}, default=None, indent=2)
        assert b"\n" in result  # indented

    def test_indent_other_falls_back_to_stdlib(self):
        result = _json_encode({"a": 1}, default=None, indent=4)
        assert b'"a"' in result

    def test_custom_default_called_for_non_serializable(self):
        def _default(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError

        result = _json_encode({"s": {1, 2}}, default=_default, indent=None)
        assert result is not None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class TestResponse:
    def test_default_status_200(self):
        r = Response(b"ok")
        assert r.status_code == 200

    def test_custom_status(self):
        r = Response(b"", status_code=404)
        assert r.status_code == 404

    def test_bytes_content(self):
        r = Response(b"hello")
        assert r.body == b"hello"

    def test_str_content_encoded(self):
        r = Response("hello")
        assert r.body == b"hello"

    def test_none_content_empty_body(self):
        r = Response(None)
        assert r.body == b""

    def test_invalid_content_raises(self):
        with pytest.raises(TypeError):
            Response(12345)

    def test_headers_instance(self):
        r = Response(b"")
        assert isinstance(r.headers, MutableHeaders)

    def test_media_type_set_in_headers(self):
        r = Response(b"", media_type="text/plain")
        assert r.headers.get("content-type") is not None

    def test_custom_headers(self):
        r = Response(b"", headers={"x-custom": "value"})
        assert r.headers.get("x-custom") == "value"

    def test_content_type_charset_appended_for_text(self):
        r = Response("hello", media_type="text/html")
        ct = r.headers.get("content-type")
        assert ct is not None
        assert "charset" in ct

    def test_no_charset_for_binary_type(self):
        r = Response(b"data", media_type="application/octet-stream")
        ct = r.headers.get("content-type") or ""
        assert "charset" not in ct

    def test_set_cookie(self):
        r = Response(b"")
        r.set_cookie("session", "abc", httponly=True)
        cookies = r.headers.getlist("set-cookie")
        assert any("session=abc" in c for c in cookies)
        assert any("HttpOnly" in c for c in cookies)

    def test_set_cookie_max_age(self):
        r = Response(b"")
        r.set_cookie("x", "val", max_age=3600)
        cookies = r.headers.getlist("set-cookie")
        assert any("Max-Age=3600" in c for c in cookies)

    def test_set_cookie_secure(self):
        r = Response(b"")
        r.set_cookie("x", "v", secure=True)
        cookies = r.headers.getlist("set-cookie")
        assert any("Secure" in c for c in cookies)

    def test_set_cookie_domain(self):
        r = Response(b"")
        r.set_cookie("x", "v", domain="example.com")
        cookies = r.headers.getlist("set-cookie")
        assert any("Domain=example.com" in c for c in cookies)

    def test_set_cookie_expires(self):
        r = Response(b"")
        r.set_cookie("x", "v", expires=9999)
        cookies = r.headers.getlist("set-cookie")
        # After expires timestamp is formatted as HTTP date
        assert any("Expires=" in c for c in cookies)
        # Should contain a properly formatted date like "Thu, 01 Jan 1970 02:46:39 GMT"
        assert any("GMT" in c for c in cookies)

    def test_delete_cookie_sets_max_age_zero(self):
        r = Response(b"")
        r.delete_cookie("session")
        cookies = r.headers.getlist("set-cookie")
        assert any("Max-Age=0" in c for c in cookies)

    def test_set_cookie_rejects_crlf_in_key(self):
        r = Response(b"")
        with pytest.raises(ValueError, match="CR or LF"):
            r.set_cookie("key\r\nevil", "value")

    def test_set_cookie_rejects_crlf_in_value(self):
        r = Response(b"")
        with pytest.raises(ValueError, match="CR or LF"):
            r.set_cookie("key", "value\nX-Injected: evil")

    @pytest.mark.asyncio
    async def test_asgi_call_sends_messages(self):
        r = Response(b"body", status_code=200)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 200
        assert messages[1]["type"] == "http.response.body"
        assert messages[1]["body"] == b"body"

    @pytest.mark.asyncio
    async def test_asgi_sets_content_length(self):
        r = Response(b"hello")
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        start = messages[0]
        headers_dict = dict(start["headers"])
        assert b"content-length" in headers_dict


# ---------------------------------------------------------------------------
# JSONResponse
# ---------------------------------------------------------------------------


class TestJSONResponse:
    def test_media_type(self):
        r = JSONResponse({"a": 1})
        assert r.media_type == "application/json"

    def test_body_is_json(self):

        r = JSONResponse({"key": "value"})
        data = json.loads(r.body)
        assert data == {"key": "value"}

    def test_datetime_serialization(self):

        r = JSONResponse({"dt": datetime.datetime(2024, 1, 1)})
        data = json.loads(r.body)
        assert "2024" in data["dt"]

    def test_date_serialization(self):

        r = JSONResponse({"d": datetime.date(2024, 6, 1)})
        data = json.loads(r.body)
        assert "2024-06-01" in data["d"]

    def test_uuid_serialization(self):

        uid = uuid.uuid4()
        r = JSONResponse({"id": uid})
        data = json.loads(r.body)
        assert data["id"] == str(uid)

    def test_non_serializable_raises(self):
        with pytest.raises(TypeError):
            JSONResponse({"fn": lambda: None})

    def test_indent_parameter(self):
        r = JSONResponse({"a": 1}, indent=2)
        assert b"\n" in r.body

    def test_custom_status_code(self):
        r = JSONResponse({}, status_code=201)
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# HTMLResponse
# ---------------------------------------------------------------------------


class TestHTMLResponse:
    def test_media_type(self):
        r = HTMLResponse("<h1>Hello</h1>")
        assert r.media_type == "text/html"

    def test_body_encoding(self):
        r = HTMLResponse("<p>Test</p>")
        assert b"<p>Test</p>" in r.body

    def test_template_and_content_raises(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            HTMLResponse(content="<p>hi</p>", template="index.html")

    def test_render_rejects_dotdot_in_template_name(self):
        with pytest.raises(ValueError, match="Invalid template name"):
            HTMLResponse(template="../secret.html")

    def test_render_rejects_absolute_template_name(self):
        with pytest.raises(ValueError, match="Invalid template name"):
            HTMLResponse(template="/etc/passwd")


# ---------------------------------------------------------------------------
# PlainTextResponse
# ---------------------------------------------------------------------------


class TestPlainTextResponse:
    def test_media_type(self):
        r = PlainTextResponse("hello")
        assert r.media_type == "text/plain"

    def test_body(self):
        r = PlainTextResponse("world")
        assert b"world" in r.body


# ---------------------------------------------------------------------------
# RedirectResponse
# ---------------------------------------------------------------------------


class TestRedirectResponse:
    def test_default_307(self):
        r = RedirectResponse("/new-url")
        assert r.status_code == 307

    def test_location_header(self):
        r = RedirectResponse("/destination")
        assert r.headers.get("location") == "/destination"

    def test_custom_301(self):
        r = RedirectResponse("/perm", status_code=301)
        assert r.status_code == 301

    def test_redirect_rejects_crlf_in_url(self):
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse("/ok\r\nX-Injected: evil")

    def test_redirect_rejects_lf_in_url(self):
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse("/ok\nX-Injected: evil")


# ---------------------------------------------------------------------------
# StreamingResponse
# ---------------------------------------------------------------------------


class TestStreamingResponse:
    @pytest.mark.asyncio
    async def test_async_generator(self):
        async def _gen():
            yield b"chunk1"
            yield b"chunk2"

        r = StreamingResponse(_gen())
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        assert any(m["body"] == b"chunk1" for m in body_messages)

    @pytest.mark.asyncio
    async def test_callable_generator(self):
        async def _gen():
            yield b"data"

        r = StreamingResponse(_gen)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        assert any(b"data" in m["body"] for m in body_messages)

    @pytest.mark.asyncio
    async def test_sync_iterator(self):
        def _gen():
            yield b"sync"

        r = StreamingResponse(_gen())
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body_messages = [m for m in messages if m["type"] == "http.response.body"]
        assert any(m["body"] == b"sync" for m in body_messages)

    def test_default_media_type(self):
        r = StreamingResponse(iter([]))
        assert r.media_type == "application/octet-stream"

    def test_custom_media_type(self):
        r = StreamingResponse(iter([]), media_type="text/csv")
        assert r.media_type == "text/csv"


# ---------------------------------------------------------------------------
# GZipResponse
# ---------------------------------------------------------------------------


class TestGZipResponse:
    @pytest.mark.asyncio
    async def test_compresses_large_body(self):

        big = b"x" * 1000
        inner = Response(big, media_type="text/plain")
        r = GZipResponse(inner, minimum_size=100)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body = messages[-1]["body"]
        decompressed = gzip.decompress(body)
        assert decompressed == big

    @pytest.mark.asyncio
    async def test_does_not_compress_small_body(self):
        small = b"tiny"
        inner = Response(small, media_type="text/plain")
        r = GZipResponse(inner, minimum_size=1000)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body = messages[-1]["body"]
        assert body == small

    @pytest.mark.asyncio
    async def test_sets_content_encoding_header(self):
        inner = Response(b"x" * 1000)
        r = GZipResponse(inner, minimum_size=10)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        start = messages[0]
        headers_dict = dict(start["headers"])
        assert b"gzip" in headers_dict.get(b"content-encoding", b"")

    @pytest.mark.asyncio
    async def test_sets_vary_accept_encoding_when_compressed(self):
        inner = Response(b"x" * 1000, media_type="text/plain")
        r = GZipResponse(inner, minimum_size=100)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        headers_dict = dict(messages[0]["headers"])
        vary = headers_dict.get(b"vary", b"").lower()
        assert b"accept-encoding" in vary

    @pytest.mark.asyncio
    async def test_delegates_streaming_response_as_is(self):
        # GZipResponse wrapping a StreamingResponse must delegate to it
        # rather than sending an empty body.
        async def gen():
            yield b"streamed-chunk"

        inner = StreamingResponse(gen())
        r = GZipResponse(inner)
        messages = []

        async def send(msg):
            messages.append(msg)

        await r({}, None, send)
        body_parts = [
            m["body"] for m in messages if m["type"] == "http.response.body" and m["body"]
        ]
        assert b"streamed-chunk" in body_parts

    def test_default_compresslevel_is_6(self):
        inner = Response(b"data")
        r = GZipResponse(inner)
        assert r._compresslevel == 6


# ---------------------------------------------------------------------------
# FileResponse
# ---------------------------------------------------------------------------


class TestFileResponse:
    def test_allowed_dir_rejects_path_outside_root(self, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_bytes(b"secret")
        with pytest.raises(ValueError, match="outside the allowed directory"):
            FileResponse(str(outside), allowed_dir=str(tmp_path))

    def test_allowed_dir_accepts_path_inside_root(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"ok")
        r = FileResponse(str(f), allowed_dir=str(tmp_path))
        assert r.file_path == str(f.resolve())

    def test_path_is_normalized_on_construction(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"ok")
        r = FileResponse(str(f))
        assert r.file_path == str(f.resolve())

    @pytest.mark.asyncio
    async def test_serves_file_content(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        r = FileResponse(str(f))
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": []}, None, send)
        body = b"".join(m["body"] for m in sends if m["type"] == "http.response.body")
        assert body == b"hello world"

    @pytest.mark.asyncio
    async def test_sets_etag_header(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        r = FileResponse(str(f))
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": []}, None, send)
        headers = dict(sends[0]["headers"])
        assert b"etag" in headers
        assert headers[b"etag"].startswith(b'"')

    @pytest.mark.asyncio
    async def test_last_modified_is_rfc7231_format(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        r = FileResponse(str(f))
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": []}, None, send)
        headers = dict(sends[0]["headers"])
        lm = headers.get(b"last-modified", b"").decode()
        # Must be parseable as an HTTP-date (raises if malformed).
        parsed = email.utils.parsedate_to_datetime(lm)
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_if_none_match_returns_304(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")

        # First request — grab the ETag.
        r1 = FileResponse(str(f))
        sends1 = []

        async def send1(msg):
            sends1.append(msg)

        await r1({"headers": []}, None, send1)
        etag = dict(sends1[0]["headers"])[b"etag"]

        # Second request — conditional with matching ETag.
        r2 = FileResponse(str(f))
        sends2 = []

        async def send2(msg):
            sends2.append(msg)

        await r2({"headers": [(b"if-none-match", etag)]}, None, send2)
        assert sends2[0]["status"] == 304
        body = b"".join(m["body"] for m in sends2 if m["type"] == "http.response.body")
        assert body == b""

    @pytest.mark.asyncio
    async def test_if_modified_since_returns_304(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        mtime = os.path.getmtime(str(f))
        # A date one second in the future means the file is "not modified".
        future_date = email.utils.formatdate(mtime + 1, usegmt=True)

        r = FileResponse(str(f))
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": [(b"if-modified-since", future_date.encode())]}, None, send)
        assert sends[0]["status"] == 304

    @pytest.mark.asyncio
    async def test_wildcard_if_none_match_returns_304(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        r = FileResponse(str(f))
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": [(b"if-none-match", b"*")]}, None, send)
        assert sends[0]["status"] == 304

    @pytest.mark.asyncio
    async def test_filename_crlf_stripped_from_content_disposition(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        r = FileResponse(str(f), filename="evil\r\nX-Injected: true.txt")
        sends = []

        async def send(msg):
            sends.append(msg)

        await r({"headers": []}, None, send)
        headers = dict(sends[0]["headers"])
        cd = headers.get(b"content-disposition", b"").decode()
        assert "\r" not in cd
        assert "\n" not in cd
