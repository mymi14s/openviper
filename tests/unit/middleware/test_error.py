"""Unit tests for the debug traceback page and ServerErrorMiddleware."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from openviper.debug.traceback_page import (
    _esc,
    _get_source_context,
    _render_exception_chain,
    render_debug_page,
)
from openviper.middleware.error import ServerErrorMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(path: str = "/test") -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
        "asgi": {"version": "3.0"},
    }


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


# ---------------------------------------------------------------------------
# openviper.debug.traceback_page
# ---------------------------------------------------------------------------


class TestEsc:
    def test_escapes_html_chars(self) -> None:
        assert _esc("<b>") == "&lt;b&gt;"

    def test_escapes_ampersand(self) -> None:
        assert _esc("a & b") == "a &amp; b"

    def test_converts_non_strings(self) -> None:
        assert _esc(42) == "42"
        assert _esc(None) == "None"


class TestGetSourceContext:
    def test_returns_lines_around_target(self, tmp_path: Any) -> None:
        src = tmp_path / "sample.py"
        src.write_text("\n".join(f"line {i}" for i in range(1, 21)))
        lines = _get_source_context(str(src), 10, context=2)
        line_numbers = [n for n, _, _ in lines]
        assert 8 in line_numbers
        assert 12 in line_numbers

    def test_marks_current_line(self, tmp_path: Any) -> None:
        src = tmp_path / "sample.py"
        src.write_text("a\nb\nc\nd\ne\n")
        lines = _get_source_context(str(src), 3, context=1)
        current = [is_cur for _, _, is_cur in lines]
        assert any(current)
        current_lineno = [n for n, _, is_cur in lines if is_cur]
        assert current_lineno == [3]

    def test_handles_nonexistent_file(self) -> None:
        lines = _get_source_context("/no/such/file.py", 1)
        assert lines == []


class TestRenderExceptionChain:
    def test_shows_direct_cause(self) -> None:
        cause = ValueError("root cause")
        try:
            raise RuntimeError("wrapped") from cause
        except RuntimeError as exc:
            result = _render_exception_chain(exc)
        assert "direct cause" in result
        assert "ValueError" in result

    def test_shows_context(self) -> None:
        try:
            try:
                raise ValueError("original")
            except ValueError:
                raise RuntimeError("during handling")  # noqa: B904
        except RuntimeError as exc:
            result = _render_exception_chain(exc)
        assert "another exception occurred" in result
        assert "ValueError" in result

    def test_no_chain_returns_empty(self) -> None:
        exc = RuntimeError("standalone")
        assert _render_exception_chain(exc) == ""

    def test_suppressed_context_returns_empty(self) -> None:
        try:
            try:
                raise ValueError("ctx")
            except ValueError:
                raise RuntimeError("new") from None
        except RuntimeError as exc:
            result = _render_exception_chain(exc)
        assert result == ""


class TestRenderDebugPage:
    def test_returns_html_string(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            page = render_debug_page(exc)
        assert page.startswith("<!DOCTYPE html>")

    def test_contains_exception_type(self) -> None:
        try:
            raise TypeError("bad type")
        except TypeError as exc:
            page = render_debug_page(exc)
        assert "TypeError" in page

    def test_contains_exception_message(self) -> None:
        try:
            raise ValueError("unique_message_xyz")
        except ValueError as exc:
            page = render_debug_page(exc)
        assert "unique_message_xyz" in page

    def test_contains_python_version(self) -> None:
        try:
            raise RuntimeError("v")
        except RuntimeError as exc:
            page = render_debug_page(exc)
        assert sys.version.split()[0] in page

    def test_contains_traceback_section(self) -> None:
        try:
            raise RuntimeError("trace")
        except RuntimeError as exc:
            page = render_debug_page(exc)
        assert "Traceback" in page

    def test_escapes_exception_message(self) -> None:
        try:
            raise RuntimeError("<script>alert(1)</script>")
        except RuntimeError as exc:
            page = render_debug_page(exc)
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_includes_request_info_when_provided(self) -> None:
        request = MagicMock()
        request.method = "POST"
        request.path = "/api/items"
        request.headers = {"host": "localhost"}
        request.query_params = {"q": "test"}

        try:
            raise RuntimeError("req error")
        except RuntimeError as exc:
            page = render_debug_page(exc, request=request)

        assert "POST" in page
        assert "/api/items" in page

    def test_tolerates_missing_request(self) -> None:
        try:
            raise RuntimeError("no req")
        except RuntimeError as exc:
            page = render_debug_page(exc, request=None)
        assert "<!DOCTYPE html>" in page

    def test_tolerates_request_attribute_error(self) -> None:
        bad_request = object()
        try:
            raise RuntimeError("bad req")
        except RuntimeError as exc:
            page = render_debug_page(exc, request=bad_request)
        assert "<!DOCTYPE html>" in page

    def test_full_module_name_in_header(self) -> None:
        try:
            raise ValueError("mod test")
        except ValueError as exc:
            page = render_debug_page(exc)
        assert "builtins.ValueError" in page or "ValueError" in page

    def test_debug_warning_present(self) -> None:
        try:
            raise RuntimeError("warn test")
        except RuntimeError as exc:
            page = render_debug_page(exc)
        assert "DEBUG" in page


# ---------------------------------------------------------------------------
# openviper.middleware.error.ServerErrorMiddleware
# ---------------------------------------------------------------------------


class TestServerErrorMiddlewarePassthrough:
    @pytest.mark.asyncio
    async def test_passes_non_http_scopes(self) -> None:
        called: list[str] = []

        async def app(scope: Any, receive: Any, send: Any) -> None:
            called.append(scope["type"])

        mw = ServerErrorMiddleware(app, debug=True)
        await mw({"type": "lifespan"}, None, None)
        assert called == ["lifespan"]

    @pytest.mark.asyncio
    async def test_passes_through_on_success(self) -> None:
        send_messages: list[dict] = []

        async def app(scope: Any, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        async def capture_send(msg: dict) -> None:
            send_messages.append(msg)

        mw = ServerErrorMiddleware(app, debug=True)
        await mw(_make_scope(), _noop_receive, capture_send)

        statuses = [m["status"] for m in send_messages if m["type"] == "http.response.start"]
        assert statuses == [200]


class TestServerErrorMiddlewareDebugMode:
    @pytest.mark.asyncio
    async def test_returns_html_debug_page_on_error(self) -> None:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("intentional error")

        send_messages: list[dict] = []

        async def capture_send(msg: dict) -> None:
            send_messages.append(msg)

        mw = ServerErrorMiddleware(app, debug=True)
        await mw(_make_scope(), _noop_receive, capture_send)

        start = next(m for m in send_messages if m["type"] == "http.response.start")
        body_msg = next(m for m in send_messages if m["type"] == "http.response.body")

        assert start["status"] == 500
        content_type = dict(start["headers"]).get(b"content-type", b"")
        assert b"text/html" in content_type
        assert b"intentional error" in body_msg["body"]

    @pytest.mark.asyncio
    async def test_debug_page_contains_exception_type(self) -> None:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            raise TypeError("type mismatch")

        send_messages: list[dict] = []

        async def capture_send(msg: dict) -> None:
            send_messages.append(msg)

        mw = ServerErrorMiddleware(app, debug=True)
        await mw(_make_scope(), _noop_receive, capture_send)

        body = b"".join(m["body"] for m in send_messages if m["type"] == "http.response.body")
        assert b"TypeError" in body


class TestServerErrorMiddlewareProductionMode:
    @pytest.mark.asyncio
    async def test_returns_plain_500_on_error(self) -> None:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("secret internal error")

        send_messages: list[dict] = []

        async def capture_send(msg: dict) -> None:
            send_messages.append(msg)

        mw = ServerErrorMiddleware(app, debug=False)
        await mw(_make_scope(), _noop_receive, capture_send)

        start = next(m for m in send_messages if m["type"] == "http.response.start")
        body_msg = next(m for m in send_messages if m["type"] == "http.response.body")

        assert start["status"] == 500
        assert body_msg["body"] == b"Internal Server Error"

    @pytest.mark.asyncio
    async def test_does_not_leak_exception_details_in_production(self) -> None:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("super secret password")

        send_messages: list[dict] = []

        async def capture_send(msg: dict) -> None:
            send_messages.append(msg)

        mw = ServerErrorMiddleware(app, debug=False)
        await mw(_make_scope(), _noop_receive, capture_send)

        body = b"".join(m["body"] for m in send_messages if m["type"] == "http.response.body")
        assert b"super secret password" not in body


class TestServerErrorMiddlewareAfterResponseStarted:
    @pytest.mark.asyncio
    async def test_reraises_when_response_already_started(self) -> None:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("mid-stream error")

        sent: list[dict] = []

        async def capture_send(msg: dict) -> None:
            sent.append(msg)

        mw = ServerErrorMiddleware(app, debug=True)
        with pytest.raises(RuntimeError, match="mid-stream error"):
            await mw(_make_scope(), _noop_receive, capture_send)
