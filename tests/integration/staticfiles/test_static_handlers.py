"""Integration tests for staticfiles/handlers.py —
StaticFilesMiddleware, _discover_app_static_dirs, collect_static.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from openviper.app import OpenViper
from openviper.staticfiles.handlers import (
    StaticFilesMiddleware,
    collect_static,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_static(tmpdir: str, content: str = "hello") -> StaticFilesMiddleware:
    static_path = Path(tmpdir)
    (static_path / "style.css").write_text(content)
    (static_path / "script.js").write_text(content)
    inner = OpenViper()
    return StaticFilesMiddleware(inner, url_path="/static", directories=[static_path])


# ---------------------------------------------------------------------------
# StaticFilesMiddleware — basic serving
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serves_css_file():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp, "body {}")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/static/style.css")
    assert resp.status_code == 200
    assert "body" in resp.text
    assert "text/css" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_serves_js_file():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp, "console.log('hi')")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/static/script.js")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_returns_404_for_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/static/nonexistent.txt")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_static_path_passes_through_to_app():
    with tempfile.TemporaryDirectory() as tmp:
        inner = OpenViper()
        from openviper.http.request import Request
        from openviper.http.response import JSONResponse

        @inner.get("/api/data")
        async def data(request: Request):
            return JSONResponse({"ok": True})

        app = StaticFilesMiddleware(inner, url_path="/static", directories=[Path(tmp)])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/api/data")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_head_request_returns_headers_no_body():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp, "hello world")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.head("/static/style.css")
    assert resp.status_code == 200
    assert resp.content == b""
    assert "content-length" in resp.headers


@pytest.mark.asyncio
async def test_405_for_post_to_static():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post("/static/style.css")
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_400_for_path_traversal():
    """../ in path is rejected with 400. Bypass httpx URL normalization via raw ASGI."""
    with tempfile.TemporaryDirectory() as tmp:
        static_path = Path(tmp)
        (static_path / "style.css").write_text("body{}")
        inner = OpenViper()
        app = StaticFilesMiddleware(inner, url_path="/static", directories=[static_path])

        messages = []

        async def fake_send(msg):
            messages.append(msg)

        async def fake_receive():
            return {"type": "http.disconnect"}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/static/../etc/passwd",
            "query_string": b"",
            "headers": [],
        }
        await app(scope, fake_receive, fake_send)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 400


@pytest.mark.asyncio
async def test_etag_304_not_modified():
    """Second request with matching ETag returns 304."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app_with_static(tmp, "cached content")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r1 = await client.get("/static/style.css")
            etag = r1.headers.get("etag")
            assert etag
            r2 = await client.get("/static/style.css", headers={"If-None-Match": etag})
    assert r2.status_code == 304


@pytest.mark.asyncio
async def test_non_http_scope_passes_through():
    """Lifespan / websocket scopes bypass static serving."""
    received = []

    async def inner(scope, receive, send):
        received.append(scope["type"])

    mw = StaticFilesMiddleware(inner, url_path="/static", directories=[])
    await mw({"type": "lifespan"}, None, None)
    assert "lifespan" in received


# ---------------------------------------------------------------------------
# collect_static
# ---------------------------------------------------------------------------


def test_collect_static_copies_files():
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            (src_path / "app.js").write_text("alert('hi')")
            (src_path / "sub").mkdir()
            (src_path / "sub" / "deep.css").write_text("p{}")

            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=[],
            ):
                count = collect_static([src_path], dst)

            assert count == 2
            assert (Path(dst) / "app.js").exists()
            assert (Path(dst) / "sub" / "deep.css").exists()


def test_collect_static_clear_removes_dest():
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            # Pre-populate dest with a stale file
            stale = dst_path / "stale.txt"
            stale.write_text("old")

            (src_path / "new.js").write_text("new")

            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=[],
            ):
                count = collect_static([src_path], dst_path, clear=True)

            assert count == 1
            assert not stale.exists()
            assert (dst_path / "new.js").exists()


def test_collect_static_skips_nonexistent_source():
    with tempfile.TemporaryDirectory() as dst:
        with patch(
            "openviper.staticfiles.handlers._discover_app_static_dirs",
            return_value=[],
        ):
            count = collect_static(["/nonexistent/path/xyz"], dst)
    assert count == 0


def test_collect_static_skips_same_file_source_dest():
    """When source and dest are the same dir, no files should be copied (or error raised)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        (src / "file.txt").write_text("content")

        with patch(
            "openviper.staticfiles.handlers._discover_app_static_dirs",
            return_value=[],
        ):
            # Should not raise and should gracefully skip
            count = collect_static([src], src)
    assert count == 0


def test_collect_static_includes_app_static_dirs():
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            app_static = Path(src) / "app_static"
            app_static.mkdir()
            (app_static / "vendor.js").write_text("vendor")

            proj_static = Path(src) / "proj_static"
            proj_static.mkdir()
            (proj_static / "main.css").write_text("body{}")

            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=[app_static],
            ):
                count = collect_static([proj_static], dst)

            assert count == 2
            assert (Path(dst) / "vendor.js").exists()
            assert (Path(dst) / "main.css").exists()
