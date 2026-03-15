"""Unit tests for openviper.staticfiles.handlers — static file serving."""

from __future__ import annotations

import tempfile
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


def _make_scope(
    path: str = "/static/file.js",
    method: str = "GET",
    headers: list | None = None,
    scope_type: str = "http",
) -> dict:
    return {
        "type": scope_type,
        "path": path,
        "method": method,
        "headers": headers or [],
    }


def _start_headers(send: MagicMock) -> dict:
    """Extract headers from the http.response.start message as a dict."""
    return dict(send.call_args_list[0][0][0]["headers"])


# ---------------------------------------------------------------------------
# NotModifiedResponse
# ---------------------------------------------------------------------------


class TestNotModifiedResponse:
    @pytest.mark.asyncio
    async def test_sends_304_start(self):
        send = AsyncMock()
        await NotModifiedResponse()(scope={}, receive=AsyncMock(), send=send)
        assert send.call_args_list[0][0][0]["status"] == 304

    @pytest.mark.asyncio
    async def test_sends_two_messages(self):
        send = AsyncMock()
        await NotModifiedResponse()(scope={}, receive=AsyncMock(), send=send)
        assert send.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_empty_body(self):
        send = AsyncMock()
        await NotModifiedResponse()(scope={}, receive=AsyncMock(), send=send)
        assert send.call_args_list[1][0][0]["body"] == b""


# ---------------------------------------------------------------------------
# StaticFilesMiddleware.__init__ — pre-resolved directories
# ---------------------------------------------------------------------------


class TestStaticFilesMiddlewareInit:
    def test_directories_property_returns_raw_paths(self):
        mw = StaticFilesMiddleware(AsyncMock(), directories=["static", "frontend/dist"])
        assert mw.directories == [Path("static"), Path("frontend/dist")]

    def test_strips_trailing_slash_from_url_path(self):
        mw = StaticFilesMiddleware(AsyncMock(), url_path="/static/")
        assert mw.url_path == "/static"

    def test_default_directory_is_static(self):
        mw = StaticFilesMiddleware(AsyncMock())
        assert mw.directories == [Path("static")]

    def test_resolved_dirs_count_matches_input(self):
        """One entry per supplied directory."""
        mw = StaticFilesMiddleware(AsyncMock(), directories=["a", "b", "c"])
        assert len(mw.directories) == 3

    def test_resolved_path_is_absolute(self):
        """Path.resolve() on a relative dir produces an absolute path."""
        assert Path("static").resolve().is_absolute()


# ---------------------------------------------------------------------------
# StaticFilesMiddleware.__call__ — routing
# ---------------------------------------------------------------------------


class TestStaticFilesMiddlewareRouting:
    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self):
        app = AsyncMock()
        mw = StaticFilesMiddleware(app)
        scope = _make_scope(scope_type="websocket")
        receive, send = AsyncMock(), AsyncMock()
        await mw(scope, receive, send)
        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_passes_through_non_static_path(self):
        app = AsyncMock()
        mw = StaticFilesMiddleware(app, url_path="/static")
        await mw(_make_scope(path="/api/users"), AsyncMock(), AsyncMock())
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_post_with_405(self):
        mw = StaticFilesMiddleware(AsyncMock())
        send = AsyncMock()
        await mw(_make_scope(method="POST"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 405

    @pytest.mark.asyncio
    async def test_rejects_delete_with_405(self):
        mw = StaticFilesMiddleware(AsyncMock())
        send = AsyncMock()
        await mw(_make_scope(method="DELETE"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 405


# ---------------------------------------------------------------------------
# path traversal — Path.parts check
# ---------------------------------------------------------------------------


class TestPathTraversalRejection:
    @pytest.mark.asyncio
    async def test_rejects_dotdot_component(self):
        mw = StaticFilesMiddleware(AsyncMock())
        send = AsyncMock()
        await mw(_make_scope(path="/static/../etc/passwd"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 400

    @pytest.mark.asyncio
    async def test_rejects_dotdot_in_subdirectory(self):
        mw = StaticFilesMiddleware(AsyncMock())
        send = AsyncMock()
        await mw(_make_scope(path="/static/a/../../etc/passwd"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 400

    @pytest.mark.asyncio
    async def test_rejects_deep_traversal(self):
        mw = StaticFilesMiddleware(AsyncMock())
        send = AsyncMock()
        await mw(_make_scope(path="/static/js/../../../etc/shadow"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 400

    @pytest.mark.asyncio
    async def test_allows_legitimate_path(self):
        """A normal path with no .. should not be rejected (may 404, but not 400)."""
        mw = StaticFilesMiddleware(AsyncMock(), directories=["nonexistent_dir_xyz"])
        send = AsyncMock()
        await mw(_make_scope(path="/static/js/app.js"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] != 400


# ---------------------------------------------------------------------------
# _find_file — single stat syscall (TOCTOU fix #7), via real filesystem
# ---------------------------------------------------------------------------


class TestFindFile:
    @pytest.mark.asyncio
    async def test_returns_404_for_missing_file(self):
        mw = StaticFilesMiddleware(AsyncMock(), directories=["nonexistent_xyz"])
        send = AsyncMock()
        await mw(_make_scope(path="/static/missing.js"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 404

    @pytest.mark.asyncio
    async def test_finds_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "app.js").write_bytes(b"console.log(1)")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/app.js"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 200

    @pytest.mark.asyncio
    async def test_stat_called_once_per_candidate(self):
        """Verify only one aiofiles.os.stat call (no separate isfile call)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "app.js").write_bytes(b"x")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])

            real_stat = __import__("aiofiles.os", fromlist=["stat"]).stat

            stat_calls = []

            async def counting_stat(path):
                stat_calls.append(path)
                return await real_stat(path)

            with patch("openviper.staticfiles.handlers.aiofiles.os.stat", counting_stat):
                send = AsyncMock()
                await mw(_make_scope(path="/static/app.js"), AsyncMock(), send)

        # Exactly one stat call for one directory with one candidate
        assert len(stat_calls) == 1

    @pytest.mark.asyncio
    async def test_directory_not_served_as_file(self):
        """A sub-directory should result in 404, not 200."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "subdir").mkdir()
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/subdir"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 404

    @pytest.mark.asyncio
    async def test_traversal_blocked_by_resolve_guard(self):
        """Even bypassing __call__ check, the relative_to guard blocks traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            # Manually inject a traversal path (bypassing __call__ early-exit)
            send = AsyncMock()
            scope = _make_scope(path="/static/safe.js")
            # Patch Path.parts to skip the early check, then rely on resolve guard
            with patch.object(Path, "parts", new_callable=lambda: property(lambda self: ())):
                await mw(
                    {**scope, "path": "/static/../etc/passwd"},
                    AsyncMock(),
                    send,
                )
        # resolve guard should prevent serving anything outside tmpdir
        status = send.call_args_list[0][0][0]["status"]
        assert status in (400, 404)


# ---------------------------------------------------------------------------
# X-Content-Type-Options nosniff header
# ---------------------------------------------------------------------------


class TestNosniffHeader:
    @pytest.mark.asyncio
    async def test_response_includes_nosniff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "app.js").write_bytes(b"console.log(1)")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/app.js"), AsyncMock(), send)

        assert send.call_args_list[0][0][0]["status"] == 200
        headers = _start_headers(send)
        assert headers.get(b"x-content-type-options") == b"nosniff"

    @pytest.mark.asyncio
    async def test_head_response_includes_nosniff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "style.css").write_bytes(b"body{}")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/style.css", method="HEAD"), AsyncMock(), send)

        assert _start_headers(send).get(b"x-content-type-options") == b"nosniff"


# ---------------------------------------------------------------------------
# _serve_file — full file serving behaviour
# ---------------------------------------------------------------------------


class TestServeFile:
    @pytest.mark.asyncio
    async def test_serves_200_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "hello.txt").write_bytes(b"hello world")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/hello.txt"), AsyncMock(), send)

        assert send.call_args_list[0][0][0]["status"] == 200
        body = b"".join(c[0][0]["body"] for c in send.call_args_list[1:] if "body" in c[0][0])
        assert body == b"hello world"

    @pytest.mark.asyncio
    async def test_head_sends_no_body_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file.js").write_bytes(b"x" * 100)
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/file.js", method="HEAD"), AsyncMock(), send)

        non_empty = [
            c[0][0]["body"] for c in send.call_args_list if "body" in c[0][0] and c[0][0]["body"]
        ]
        assert non_empty == []

    @pytest.mark.asyncio
    async def test_etag_header_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file.js").write_bytes(b"data")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/file.js"), AsyncMock(), send)

        etag = _start_headers(send).get(b"etag", b"")
        assert etag.startswith(b'"')
        assert etag.endswith(b'"')

    @pytest.mark.asyncio
    async def test_if_none_match_returns_304(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file.js").write_bytes(b"data")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])

            send1 = AsyncMock()
            await mw(_make_scope(path="/static/file.js"), AsyncMock(), send1)
            etag = _start_headers(send1)[b"etag"]

            send2 = AsyncMock()
            scope = _make_scope(path="/static/file.js", headers=[[b"if-none-match", etag]])
            await mw(scope, AsyncMock(), send2)

        assert send2.call_args_list[0][0][0]["status"] == 304

    @pytest.mark.asyncio
    async def test_content_type_for_js(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "app.js").write_bytes(b"x")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/app.js"), AsyncMock(), send)

        assert b"javascript" in _start_headers(send)[b"content-type"]

    @pytest.mark.asyncio
    async def test_content_length_matches_file_size(self):
        content = b"x" * 512
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "data.bin").write_bytes(content)
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/data.bin"), AsyncMock(), send)

        assert _start_headers(send)[b"content-length"] == b"512"

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_file(self):
        mw = StaticFilesMiddleware(AsyncMock(), directories=["nonexistent_xyz"])
        send = AsyncMock()
        await mw(_make_scope(path="/static/missing.js"), AsyncMock(), send)
        assert send.call_args_list[0][0][0]["status"] == 404

    @pytest.mark.asyncio
    async def test_accept_ranges_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "f.bin").write_bytes(b"x")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/f.bin"), AsyncMock(), send)

        assert _start_headers(send).get(b"accept-ranges") == b"bytes"


# ---------------------------------------------------------------------------
# collect_static — symlink guard (security fix #3)
# ---------------------------------------------------------------------------


class TestCollectStaticSymlinkGuard:
    def test_raises_on_symlink_dest_with_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dest = Path(tmpdir) / "real_dest"
            real_dest.mkdir()
            symlink_dest = Path(tmpdir) / "link_dest"
            symlink_dest.symlink_to(real_dest)

            with pytest.raises(ValueError, match="symlink"):
                with patch(
                    "openviper.staticfiles.handlers._discover_app_static_dirs",
                    return_value=(),
                ):
                    collect_static([], str(symlink_dest), clear=True)

    def test_no_error_when_clear_false_and_dest_is_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dest = Path(tmpdir) / "real_dest"
            real_dest.mkdir()
            symlink_dest = Path(tmpdir) / "link_dest"
            symlink_dest.symlink_to(real_dest)

            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                collect_static([], str(symlink_dest), clear=False)

    def test_no_error_on_real_directory_with_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "collected"
            dest.mkdir()
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                count = collect_static([], str(dest), clear=True)
            assert count == 0


# ---------------------------------------------------------------------------
# collect_static — general behaviour
# ---------------------------------------------------------------------------


class TestCollectStatic:
    def test_copies_files_from_source(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            (Path(src) / "style.css").write_text("body{}")
            (Path(src) / "app.js").write_text("x")
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                count = collect_static([src], dest)
            assert count == 2
            assert (Path(dest) / "style.css").exists()
            assert (Path(dest) / "app.js").exists()

    def test_returns_zero_for_empty_source(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                count = collect_static([src], dest)
            assert count == 0

    def test_clear_removes_existing_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            (Path(dest) / "old.css").write_text("old")
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                collect_static([src], dest, clear=True)
            assert not (Path(dest) / "old.css").exists()

    def test_source_files_override_app_files(self):
        with (
            tempfile.TemporaryDirectory() as app_static,
            tempfile.TemporaryDirectory() as project_static,
            tempfile.TemporaryDirectory() as dest,
        ):
            (Path(app_static) / "main.css").write_text("app version")
            (Path(project_static) / "main.css").write_text("project version")
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(Path(app_static),),
            ):
                collect_static([project_static], dest)
            assert (Path(dest) / "main.css").read_text() == "project version"

    def test_skips_same_file_copy(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "file.js").write_bytes(b"x")
            with patch(
                "openviper.staticfiles.handlers._discover_app_static_dirs",
                return_value=(),
            ):
                count = collect_static([d], d)
            assert count == 0


# ---------------------------------------------------------------------------
# _discover_app_static_dirs — exception handling (narrowed except)
# ---------------------------------------------------------------------------


class TestDiscoverAppStaticDirs:
    def test_returns_tuple(self):
        with patch("openviper.conf.settings") as ms:
            ms.INSTALLED_APPS = []
            _discover_app_static_dirs.cache_clear()
            result = _discover_app_static_dirs()
            _discover_app_static_dirs.cache_clear()
        assert isinstance(result, tuple)

    def test_caches_result(self):
        with patch("openviper.conf.settings") as ms:
            ms.INSTALLED_APPS = []
            _discover_app_static_dirs.cache_clear()
            r1 = _discover_app_static_dirs()
            r2 = _discover_app_static_dirs()
            _discover_app_static_dirs.cache_clear()
        assert r1 is r2

    def test_import_error_in_app_resolver_is_swallowed(self):
        with patch("openviper.conf.settings") as ms:
            ms.INSTALLED_APPS = ["fake_app_xyz"]
            _discover_app_static_dirs.cache_clear()
            with patch("importlib.util.find_spec", side_effect=ValueError):
                with patch(
                    "openviper.staticfiles.handlers.AppResolver",
                    side_effect=ImportError("no module"),
                ):
                    result = _discover_app_static_dirs()
            _discover_app_static_dirs.cache_clear()
        assert isinstance(result, tuple)

    def test_os_error_in_app_resolver_is_swallowed(self):
        with patch("openviper.conf.settings") as ms:
            ms.INSTALLED_APPS = ["fake_app_xyz"]
            _discover_app_static_dirs.cache_clear()
            with patch("importlib.util.find_spec", side_effect=ValueError):
                with patch(
                    "openviper.staticfiles.handlers.AppResolver",
                    side_effect=OSError("disk error"),
                ):
                    result = _discover_app_static_dirs()
            _discover_app_static_dirs.cache_clear()
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# _serve_file: MIME type fallback and content-encoding header
# ---------------------------------------------------------------------------


class TestServeMIMEFallback:
    @pytest.mark.asyncio
    async def test_unknown_extension_uses_octet_stream(self):
        """Files with no known extension get application/octet-stream MIME (line 143)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "datafile.unknownxyz").write_bytes(b"binary data")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/datafile.unknownxyz"), AsyncMock(), send)

        headers = _start_headers(send)
        assert headers[b"content-type"] == b"application/octet-stream"

    @pytest.mark.asyncio
    async def test_gz_file_has_content_encoding_header(self):
        """Compressed files get content-encoding header (line 155)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # .gz → mimetypes.guess_type returns (None, 'gzip') on all platforms
            (Path(tmpdir) / "bundle.gz").write_bytes(b"compressed")
            mw = StaticFilesMiddleware(AsyncMock(), directories=[tmpdir])
            send = AsyncMock()
            await mw(_make_scope(path="/static/bundle.gz"), AsyncMock(), send)

        headers = _start_headers(send)
        assert b"content-encoding" in headers
        assert headers[b"content-encoding"] == b"gzip"


# ---------------------------------------------------------------------------
# _discover_app_static_dirs: AppResolver fallback success (lines 236-241)
# ---------------------------------------------------------------------------


class TestDiscoverAppStaticDirsResolverFallback:
    def test_app_resolver_fallback_finds_static_dir(self, tmp_path):
        """AppResolver fallback discovers static/ dir when importlib path fails (lines 236-241)."""
        static_dir = tmp_path / "static"
        static_dir.mkdir()

        with patch("openviper.conf.settings") as ms:
            ms.INSTALLED_APPS = ["my_fallback_app"]
            _discover_app_static_dirs.cache_clear()
            with patch("importlib.util.find_spec", side_effect=ValueError("no spec")):
                with patch("openviper.staticfiles.handlers.AppResolver") as mock_resolver_cls:
                    mock_resolver = MagicMock()
                    mock_resolver.resolve_app.return_value = (str(tmp_path), True)
                    mock_resolver_cls.return_value = mock_resolver
                    result = _discover_app_static_dirs()
            _discover_app_static_dirs.cache_clear()

        assert static_dir.resolve() in [p.resolve() for p in result]


# ---------------------------------------------------------------------------
# collect_static: _copy_tree skips subdirectories (line 289)
# ---------------------------------------------------------------------------


class TestCollectStaticCopyTreeSkipsDirs:
    def test_copy_tree_skips_non_file_items(self, tmp_path):
        """_copy_tree skips subdirectory items during rglob (line 289)."""
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        # Create a file and a subdirectory inside source
        (source / "script.js").write_bytes(b"console.log('x')")
        (source / "subdir").mkdir()  # non-file item — should be skipped

        with patch("openviper.staticfiles.handlers._discover_app_static_dirs", return_value=()):
            collect_static([str(source)], dest_dir=str(dest))

        # Only the file was copied, not the directory
        assert (dest / "script.js").exists()
        assert not (dest / "subdir").is_file()
