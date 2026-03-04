"""Unit tests for openviper.staticfiles.handlers."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.staticfiles.handlers import (
    NotModifiedResponse,
    StaticFilesMiddleware,
    _discover_app_static_dirs,
    collect_static,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(path="/static/style.css", method="GET", headers=None, type_="http"):
    return {
        "type": type_,
        "path": path,
        "method": method,
        "headers": headers or [],
    }


# ---------------------------------------------------------------------------
# NotModifiedResponse
# ---------------------------------------------------------------------------


class TestNotModifiedResponse:
    @pytest.mark.asyncio
    async def test_sends_304_start_event(self):
        resp = NotModifiedResponse()
        scope: dict = {}
        receive = AsyncMock()
        send_calls = []

        async def send(event):
            send_calls.append(event)

        await resp(scope, receive, send)
        assert send_calls[0]["type"] == "http.response.start"
        assert send_calls[0]["status"] == 304

    @pytest.mark.asyncio
    async def test_sends_empty_body(self):
        resp = NotModifiedResponse()
        send_calls = []

        async def send(event):
            send_calls.append(event)

        await resp({}, AsyncMock(), send)
        body_event = send_calls[1]
        assert body_event["type"] == "http.response.body"
        assert body_event["body"] == b""


# ---------------------------------------------------------------------------
# StaticFilesMiddleware – non-HTTP / path mismatch pass-through
# ---------------------------------------------------------------------------


class TestStaticFilesMiddlewarePassThrough:
    @pytest.mark.asyncio
    async def test_non_http_scope_passed_to_app(self):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app)
        scope = _make_scope(type_="websocket")
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        inner_app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_non_matching_path_passed_to_app(self):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static")
        scope = _make_scope(path="/api/data")
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        inner_app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_exact_prefix_without_trailing_slash_passed_to_app(self):
        """'/static' without '/' after it should pass through."""
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static")
        scope = _make_scope(path="/static")
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        inner_app.assert_awaited_once_with(scope, receive, send)


# ---------------------------------------------------------------------------
# StaticFilesMiddleware – request validation
# ---------------------------------------------------------------------------


class TestStaticFilesMiddlewareValidation:
    @pytest.mark.asyncio
    async def test_post_method_returns_405(self):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static")
        scope = _make_scope(path="/static/style.css", method="POST")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 405

    @pytest.mark.asyncio
    async def test_delete_method_returns_405(self):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static")
        scope = _make_scope(path="/static/style.css", method="DELETE")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 405

    @pytest.mark.asyncio
    async def test_path_traversal_returns_400(self):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static")
        scope = _make_scope(path="/static/../secret.txt", method="GET")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_file_not_found_returns_404(self, tmp_path):
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(path="/static/missing.css")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 404


# ---------------------------------------------------------------------------
# StaticFilesMiddleware – file serving
# ---------------------------------------------------------------------------


class TestStaticFilesMiddlewareServe:
    @pytest.mark.asyncio
    async def test_serves_existing_css_file(self, tmp_path):
        css = tmp_path / "style.css"
        css.write_text("body { color: red; }")
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(path="/static/style.css")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["type"] == "http.response.start"
        assert events[0]["status"] == 200
        # body should contain file content
        body = b"".join(e["body"] for e in events[1:] if "body" in e)
        assert b"body" in body

    @pytest.mark.asyncio
    async def test_head_request_no_body(self, tmp_path):
        css = tmp_path / "style.css"
        css.write_text("body { margin: 0; }")
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(path="/static/style.css", method="HEAD")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 200
        # All body events should be empty
        for e in events[1:]:
            if "body" in e:
                assert e["body"] == b""

    @pytest.mark.asyncio
    async def test_etag_match_returns_304(self, tmp_path):
        css = tmp_path / "style.css"
        css.write_text("body {}")
        stat = css.stat()
        etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'.encode()

        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(
            path="/static/style.css",
            headers=[[b"if-none-match", etag]],
        )
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        assert events[0]["status"] == 304

    @pytest.mark.asyncio
    async def test_content_type_set_for_css(self, tmp_path):
        css = tmp_path / "style.css"
        css.write_text("p {}")
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(path="/static/style.css")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        headers = dict(events[0]["headers"])
        assert b"text/css" in headers.get(b"content-type", b"")

    @pytest.mark.asyncio
    async def test_unknown_mime_falls_back_to_octet_stream(self, tmp_path):
        f = tmp_path / "data.xyz123"
        f.write_bytes(b"\x00\x01\x02")
        inner_app = AsyncMock()
        middleware = StaticFilesMiddleware(inner_app, url_path="/static", directories=[tmp_path])
        scope = _make_scope(path="/static/data.xyz123")
        events = []

        async def send(e):
            events.append(e)

        await middleware(scope, AsyncMock(), send)
        headers = dict(events[0]["headers"])
        assert b"application/octet-stream" in headers.get(b"content-type", b"")


# ---------------------------------------------------------------------------
# StaticFilesMiddleware – _find_file
# ---------------------------------------------------------------------------


class TestFindFile:
    def test_returns_none_when_file_not_found(self, tmp_path):
        middleware = StaticFilesMiddleware(MagicMock(), directories=[tmp_path])
        assert middleware._find_file("nonexistent.css") is None

    def test_returns_path_when_file_exists(self, tmp_path):
        f = tmp_path / "main.js"
        f.write_text("console.log(1)")
        middleware = StaticFilesMiddleware(MagicMock(), directories=[tmp_path])
        result = middleware._find_file("main.js")
        assert result == f

    def test_checks_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "d1"
        dir1.mkdir()
        dir2 = tmp_path / "d2"
        dir2.mkdir()
        f = dir2 / "app.js"
        f.write_text("var x = 1;")
        middleware = StaticFilesMiddleware(MagicMock(), directories=[dir1, dir2])
        result = middleware._find_file("app.js")
        assert result == f

    def test_rejects_traversal_outside_directory(self, tmp_path):
        """Files resolving outside the directory are skipped."""
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")
        sub = tmp_path / "sub"
        sub.mkdir()
        middleware = StaticFilesMiddleware(MagicMock(), directories=[sub])
        # traversal from sub → tmp_path/secret.txt
        result = middleware._find_file("../secret.txt")
        assert result is None


# ---------------------------------------------------------------------------
# StaticFilesMiddleware – _send_response
# ---------------------------------------------------------------------------


class TestSendResponse:
    @pytest.mark.asyncio
    async def test_sends_correct_status(self):
        events = []

        async def send(e):
            events.append(e)

        await StaticFilesMiddleware._send_response(send, 404, b"Not Found", "text/plain")
        assert events[0]["status"] == 404

    @pytest.mark.asyncio
    async def test_sends_body(self):
        events = []

        async def send(e):
            events.append(e)

        await StaticFilesMiddleware._send_response(send, 200, b"OK", "text/plain")
        assert events[1]["body"] == b"OK"

    @pytest.mark.asyncio
    async def test_content_length_header_matches_body(self):
        events = []

        async def send(e):
            events.append(e)

        body = b"Hello World"
        await StaticFilesMiddleware._send_response(send, 200, body, "text/plain")
        headers = dict(events[0]["headers"])
        assert headers[b"content-length"] == str(len(body)).encode()


# ---------------------------------------------------------------------------
# _discover_app_static_dirs
# ---------------------------------------------------------------------------


class TestDiscoverAppStaticDirs:
    def test_returns_list(self):
        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = []
            result = _discover_app_static_dirs()
        assert isinstance(result, list)

    def test_includes_openviper_admin_automatically(self):
        """Even with empty INSTALLED_APPS, openviper.admin is always searched."""
        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = []
            with patch("openviper.staticfiles.handlers.importlib.util.find_spec") as mock_spec:
                mock_spec.return_value = None  # not found
                _discover_app_static_dirs()
        # openviper.admin should be in what was searched
        calls = [call[0][0] for call in mock_spec.call_args_list]
        assert "openviper.admin" in calls

    def test_skips_app_when_spec_is_none(self):
        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = ["myapp"]
            with patch(
                "openviper.staticfiles.handlers.importlib.util.find_spec", return_value=None
            ):
                result = _discover_app_static_dirs()
        # Should not raise, returns list (possibly empty)
        assert isinstance(result, list)

    def test_fallback_to_app_resolver_on_import_error(self, tmp_path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()

        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (str(tmp_path), True)

        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = ["localapp"]
            with patch(
                "openviper.staticfiles.handlers.importlib.util.find_spec",
                side_effect=[ImportError, None],
            ):
                with patch(
                    "openviper.staticfiles.handlers.AppResolver", return_value=mock_resolver
                ):
                    result = _discover_app_static_dirs()

        assert static_dir in result

    def test_fallback_resolver_not_found_skips(self):
        mock_resolver = MagicMock()
        mock_resolver.resolve_app.return_value = (None, False)

        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = ["unknownapp"]
            with patch(
                "openviper.staticfiles.handlers.importlib.util.find_spec",
                side_effect=[ImportError, None],
            ):
                with patch(
                    "openviper.staticfiles.handlers.AppResolver", return_value=mock_resolver
                ):
                    result = _discover_app_static_dirs()

        assert result == [] or len(result) <= 1  # only openviper.admin (also not found)

    def test_found_static_dir_included(self, tmp_path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")

        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = ["myapp"]
            with patch(
                "openviper.staticfiles.handlers.importlib.util.find_spec",
                return_value=mock_spec,
            ):
                result = _discover_app_static_dirs()

        assert static_dir in result

    def test_deduplicates_directories(self, tmp_path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")

        with patch("openviper.staticfiles.handlers.settings") as ms:
            ms.INSTALLED_APPS = ["myapp", "myapp"]  # duplicate
            with patch(
                "openviper.staticfiles.handlers.importlib.util.find_spec",
                return_value=mock_spec,
            ):
                result = _discover_app_static_dirs()

        assert result.count(static_dir) == 1


# ---------------------------------------------------------------------------
# collect_static
# ---------------------------------------------------------------------------


class TestCollectStatic:
    def test_copies_files_to_dest(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.css").write_text("body {}")
        dest = tmp_path / "dest"

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            count = collect_static([src], dest)

        assert count == 1
        assert (dest / "main.css").exists()

    def test_returns_correct_count(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.js").write_text("var a;")
        (src / "b.js").write_text("var b;")
        dest = tmp_path / "dest"

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            count = collect_static([src], dest)

        assert count == 2

    def test_clear_removes_dest(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "old.css").write_text("stale")

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            collect_static([src], dest, clear=True)

        assert not (dest / "old.css").exists()

    def test_clear_not_set_preserves_existing_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        existing = dest / "old.css"
        existing.write_text("old content")

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            collect_static([src], dest, clear=False)

        assert existing.exists()

    def test_collects_from_app_static_dirs(self, tmp_path):
        app_static = tmp_path / "app_static"
        app_static.mkdir()
        (app_static / "widget.js").write_text("// widget")
        dest = tmp_path / "dest"

        with patch(
            "openviper.staticfiles.handlers._discover_app_static_dirs",
            return_value=[app_static],
        ):
            count = collect_static([], dest)

        assert count == 1
        assert (dest / "widget.js").exists()

    def test_skips_source_not_existing(self, tmp_path):
        dest = tmp_path / "dest"
        nonexistent = tmp_path / "nope"

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            count = collect_static([nonexistent], dest)

        assert count == 0

    def test_source_same_as_dest_skips_copy(self, tmp_path):
        """When copying to itself, nothing should be duplicated/errored."""
        (tmp_path / "style.css").write_text("p {}")

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            count = collect_static([tmp_path], tmp_path, clear=False)

        # Same-file copies are skipped, count should be 0
        assert count == 0

    def test_nested_files_are_copied(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "js"
        sub.mkdir(parents=True)
        (sub / "app.js").write_text("var app;")
        dest = tmp_path / "dest"

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            count = collect_static([src], dest)

        assert count == 1
        assert (dest / "js" / "app.js").exists()

    def test_creates_dest_if_not_exists(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.js").write_text("a")
        dest = tmp_path / "nonexistent_dest"

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=[]):
            collect_static([src], dest)

        assert dest.is_dir()
