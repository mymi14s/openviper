"""Unit tests for openviper.middleware (base, cors, csrf, security, ratelimit)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from openviper.conf import settings
from openviper.middleware.base import BaseMiddleware, build_middleware_stack
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.csrf import (
    CSRFMiddleware,
    _extract_cookie_value,
    _generate_csrf_token,
    _mask_csrf_token,
    _verify_csrf_token,
)
from openviper.middleware.security import SecurityMiddleware
from openviper.middleware.security import SecurityMiddleware as SM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scope(
    method="GET",
    path="/",
    headers=None,
    scheme="http",
    type_="http",
):
    return {
        "type": type_,
        "method": method.upper(),
        "path": path,
        "headers": headers or [],
        "scheme": scheme,
    }


class CaptureSend:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)


async def dummy_app(scope, receive, send):
    """Minimal ASGI app that returns 200 OK."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


# ---------------------------------------------------------------------------
# BaseMiddleware
# ---------------------------------------------------------------------------


class TestBaseMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through_to_app(self):
        messages = []

        async def app(scope, receive, send):
            messages.append("called")

        mw = BaseMiddleware(app)
        await mw({}, None, None)
        assert "called" in messages

    def test_repr(self):
        mw = BaseMiddleware(dummy_app)
        assert "BaseMiddleware" in repr(mw)


# ---------------------------------------------------------------------------
# build_middleware_stack
# ---------------------------------------------------------------------------


class TestBuildMiddlewareStack:
    @pytest.mark.asyncio
    async def test_single_middleware(self):
        order = []

        class TrackMW(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                order.append("before")
                await self.app(scope, receive, send)
                order.append("after")

        core = AsyncMock()
        stack = build_middleware_stack(core, [TrackMW])
        await stack({}, None, None)
        assert order == ["before", "after"]

    @pytest.mark.asyncio
    async def test_multiple_middlewares_order(self):
        order = []

        class MW1(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                order.append("mw1_before")
                await self.app(scope, receive, send)
                order.append("mw1_after")

        class MW2(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                order.append("mw2_before")
                await self.app(scope, receive, send)
                order.append("mw2_after")

        core = AsyncMock()
        # MW1 is outermost
        stack = build_middleware_stack(core, [MW1, MW2])
        await stack({}, None, None)
        assert order.index("mw1_before") < order.index("mw2_before")

    @pytest.mark.asyncio
    async def test_middleware_with_kwargs(self):
        class ParamMW(BaseMiddleware):
            def __init__(self, app, value=None):
                super().__init__(app)
                self.value = value

            async def __call__(self, scope, receive, send):
                await self.app(scope, receive, send)

        core = AsyncMock()
        stack = build_middleware_stack(core, [(ParamMW, {"value": "test"})])
        assert isinstance(stack, ParamMW)
        assert stack.value == "test"


# ---------------------------------------------------------------------------
# CORSMiddleware
# ---------------------------------------------------------------------------


class TestCORSMiddleware:
    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)

        mw = CORSMiddleware(app, allowed_origins=["*"])
        scope = make_scope(type_="websocket")
        await mw(scope, None, None)
        assert called

    @pytest.mark.asyncio
    async def test_no_origin_header_passthrough(self):
        messages = []
        mw = CORSMiddleware(dummy_app, allowed_origins=["*"])
        scope = make_scope()
        send = CaptureSend()
        await mw(scope, None, send)
        assert any(m.get("status") == 200 for m in send.messages)

    @pytest.mark.asyncio
    async def test_preflight_allowed_origin(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["https://example.com"])
        scope = make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://example.com")],
        )
        send = CaptureSend()
        await mw(scope, None, send)
        assert send.messages[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_preflight_rejected_origin(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["https://allowed.com"])
        scope = make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://evil.com")],
        )
        send = CaptureSend()
        await mw(scope, None, send)
        # No access-control-allow-origin in response
        all_headers = dict(send.messages[0].get("headers", []))
        assert b"access-control-allow-origin" not in all_headers

    @pytest.mark.asyncio
    async def test_wildcard_allows_any_origin(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["*"])
        scope = make_scope(
            method="GET",
            headers=[(b"origin", b"https://random.io")],
        )
        send = CaptureSend()
        await mw(scope, None, send)
        # Should attach CORS header
        start_headers = dict(send.messages[0].get("headers", []))
        assert b"access-control-allow-origin" in start_headers

    def test_origin_allowed_exact_match(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["https://exact.com"])
        assert mw._origin_allowed("https://exact.com") is True
        assert mw._origin_allowed("https://other.com") is False

    def test_origin_allowed_wildcard_pattern(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["https://*.example.com"])
        assert mw._origin_allowed("https://sub.example.com") is True
        assert mw._origin_allowed("https://evil.io") is False

    def test_allow_all_origins(self):
        mw = CORSMiddleware(dummy_app, allowed_origins=["*"])
        assert mw._allow_all_origins is True

    @pytest.mark.asyncio
    async def test_credentials_header_in_preflight(self):
        mw = CORSMiddleware(
            dummy_app,
            allowed_origins=["https://app.com"],
            allow_credentials=True,
        )
        scope = make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://app.com")],
        )
        send = CaptureSend()
        await mw(scope, None, send)
        headers_dict = dict(send.messages[0]["headers"])
        assert headers_dict.get(b"access-control-allow-credentials") == b"true"


# ---------------------------------------------------------------------------
# CSRFMiddleware helpers
# ---------------------------------------------------------------------------


class TestCSRFHelpers:
    def test_generate_csrf_token_length(self):
        token = _generate_csrf_token()
        assert len(token) == 64  # secrets.token_hex(32)

    def test_generate_csrf_token_is_hex(self):
        token = _generate_csrf_token()
        int(token, 16)  # raises ValueError if not hex

    def test_mask_and_verify_token(self):
        token = _generate_csrf_token()
        secret = "test-secret"
        masked = _mask_csrf_token(token, secret)
        assert _verify_csrf_token(token, masked, secret) is True

    def test_verify_wrong_token_fails(self):
        token = _generate_csrf_token()
        secret = "test-secret"
        masked = _mask_csrf_token(token, secret)
        other_token = _generate_csrf_token()
        assert _verify_csrf_token(other_token, masked, secret) is False

    def test_verify_too_short_fails(self):
        assert _verify_csrf_token("cookie", "short", "secret") is False

    def test_extract_cookie_value(self):
        header = "session=abc; csrftoken=xyz123; other=val"
        assert _extract_cookie_value(header, "csrftoken") == "xyz123"

    def test_extract_cookie_value_not_found(self):
        assert _extract_cookie_value("a=1; b=2", "missing") == ""

    def test_extract_cookie_value_empty_header(self):
        assert _extract_cookie_value("", "name") == ""


class TestCSRFMiddleware:
    @pytest.mark.asyncio
    async def test_safe_methods_pass_through(self):
        mw = CSRFMiddleware(dummy_app, secret="s3cr3t")
        # Note: TRACE is no longer a safe method (security fix)
        for method in ("GET", "HEAD", "OPTIONS"):
            send = CaptureSend()
            scope = make_scope(method=method)
            await mw(scope, None, send)
            assert any(m.get("status") == 200 for m in send.messages)

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)

        mw = CSRFMiddleware(app, secret="s")
        await mw({"type": "websocket"}, None, None)
        assert called

    @pytest.mark.asyncio
    async def test_exempt_path_passes_through(self):
        mw = CSRFMiddleware(dummy_app, secret="s", exempt_paths=["/webhook"])
        send = CaptureSend()
        await mw(make_scope(method="POST", path="/webhook"), None, send)
        assert any(m.get("status") == 200 for m in send.messages)

    @pytest.mark.asyncio
    async def test_valid_csrf_token_passes(self):
        secret = "my-secret"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        headers = [
            (b"cookie", f"csrftoken={token}".encode()),
            (b"x-csrftoken", masked.encode()),
        ]
        mw = CSRFMiddleware(dummy_app, secret=secret)
        send = CaptureSend()
        await mw(make_scope(method="POST", headers=headers), None, send)
        assert any(m.get("status") == 200 for m in send.messages)

    @pytest.mark.asyncio
    async def test_missing_csrf_token_fails(self):
        mw = CSRFMiddleware(dummy_app, secret="s3cr3t")
        send = CaptureSend()
        await mw(make_scope(method="POST"), None, send)
        assert any(m.get("status") == 403 for m in send.messages)

    @pytest.mark.asyncio
    async def test_invalid_csrf_token_fails(self):
        headers = [
            (b"cookie", b"csrftoken=realtoken"),
            (b"x-csrftoken", b"wrongtoken_padded_to_be_long_enough_xxxxxxxxxxxx"),
        ]
        mw = CSRFMiddleware(dummy_app, secret="s3cr3t")
        send = CaptureSend()
        await mw(make_scope(method="POST", headers=headers), None, send)
        assert any(m.get("status") == 403 for m in send.messages)


# ---------------------------------------------------------------------------
# SecurityMiddleware
# ---------------------------------------------------------------------------


class TestSecurityMiddleware:
    """Security middleware tests — ALLOWED_HOSTS is set to ['*'] via patch."""

    def _scope(self, **kwargs):
        """Build scope with a host header so ALLOWED_HOSTS check passes."""
        s = make_scope(**kwargs)
        s["headers"] = s.get("headers", []) + [(b"host", b"localhost")]
        s.setdefault("server", ("localhost", 8000))
        s.setdefault("query_string", b"")
        return s

    def _mw(self, **kwargs):
        """Create SecurityMiddleware with ALLOWED_HOSTS=* patched in."""

        with patch.object(type(settings), "ALLOWED_HOSTS", new=["*"], create=True):
            return SecurityMiddleware(dummy_app, **kwargs)

    @pytest.mark.asyncio
    async def test_adds_x_content_type_options(self):
        mw = self._mw(content_type_nosniff=True)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert headers.get(b"x-content-type-options") == b"nosniff"

    @pytest.mark.asyncio
    async def test_no_x_content_type_options_when_disabled(self):
        mw = self._mw(content_type_nosniff=False)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert b"x-content-type-options" not in headers

    @pytest.mark.asyncio
    async def test_adds_x_frame_options(self):
        mw = self._mw(x_frame_options="DENY")
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert headers.get(b"x-frame-options") == b"DENY"

    @pytest.mark.asyncio
    async def test_hsts_header_added_when_positive_seconds(self):
        mw = self._mw(hsts_seconds=31536000)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert b"strict-transport-security" in headers
        hsts = headers[b"strict-transport-security"].decode()
        assert "31536000" in hsts

    @pytest.mark.asyncio
    async def test_hsts_not_added_when_zero(self):
        mw = self._mw(hsts_seconds=0)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert b"strict-transport-security" not in headers

    @pytest.mark.asyncio
    async def test_ssl_redirect(self):
        mw = self._mw(ssl_redirect=True)
        send = CaptureSend()
        scope = self._scope(scheme="http")
        await mw(scope, None, send)
        statuses = [m.get("status") for m in send.messages]
        assert 301 in statuses

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self):
        called = []

        async def noop_app(scope, receive, send):
            called.append(True)

        with patch.object(type(settings), "ALLOWED_HOSTS", new=["*"], create=True):
            mw = SM(noop_app)
        send = CaptureSend()
        await mw({"type": "lifespan"}, None, send)
        assert called

    @pytest.mark.asyncio
    async def test_xss_filter_header(self):
        mw = self._mw(xss_filter=True)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        assert b"x-xss-protection" in headers

    @pytest.mark.asyncio
    async def test_hsts_include_subdomains(self):
        mw = self._mw(hsts_seconds=3600, hsts_include_subdomains=True)
        send = CaptureSend()
        await mw(self._scope(), None, send)
        headers = dict(send.messages[0].get("headers", []))
        hsts = headers.get(b"strict-transport-security", b"").decode()
        assert "includeSubDomains" in hsts
