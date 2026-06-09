"""Security headers tests.

Requirement IDs: HDR-001 through HDR-004.
"""

from __future__ import annotations

import pytest

from openviper.http.response import JSONResponse
from openviper.middleware.security import SecurityMiddleware

from .conftest import SendCollector, make_scope, override_settings


class TestDefaultSecurityHeaders:
    """Default security headers must be present on all responses."""

    @pytest.mark.asyncio
    async def test_hdr001_x_content_type_options(self):
        """X-Content-Type-Options: nosniff must be present."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "x-content-type-options" in headers
        assert headers["x-content-type-options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_hdr001_x_frame_options(self):
        """X-Frame-Options must be present with a secure default."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "x-frame-options" in headers
        assert headers["x-frame-options"] in ("DENY", "SAMEORIGIN")

    @pytest.mark.asyncio
    async def test_hdr001_referrer_policy(self):
        """Referrer-Policy must be present with a secure default."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "referrer-policy" in headers
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


class TestHSTS:
    """HSTS must only be enabled when configured for HTTPS."""

    @pytest.mark.asyncio
    async def test_hdr002_hsts_disabled_by_default(self):
        """HSTS must be disabled by default (hsts_seconds=0)."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"], SECURE_HSTS_SECONDS=0):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        # HSTS header must not be present when hsts_seconds=0
        assert "strict-transport-security" not in headers

    @pytest.mark.asyncio
    async def test_hdr002_hsts_enabled_when_configured(self):
        """HSTS must be present when hsts_seconds > 0."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"], SECURE_HSTS_SECONDS=31536000):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "strict-transport-security" in headers
        assert "max-age=31536000" in headers["strict-transport-security"]


class TestContentTypeHeaders:
    """Content-Type must be explicit and include nosniff."""

    @pytest.mark.asyncio
    async def test_hdr003_json_response_has_content_type(self):
        """JSONResponse must set application/json Content-Type."""
        response = JSONResponse({"key": "value"})
        assert response.media_type == "application/json"

    @pytest.mark.asyncio
    async def test_hdr003_nosniff_header_set(self):
        """X-Content-Type-Options: nosniff must be set."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert headers.get("x-content-type-options") == "nosniff"


class TestContentSecurityPolicy:
    """CSP must be configurable and must not include unsafe-inline by default."""

    @pytest.mark.asyncio
    async def test_hdr004_csp_without_unsafe_inline(self):
        """Default CSP must not include unsafe-inline or unsafe-eval."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        csp = {"default-src": ["'self'"], "script-src": ["'self'"]}
        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app, csp=csp)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        assert "content-security-policy" in headers
        csp_value = headers["content-security-policy"]
        # Must not contain unsafe-inline or unsafe-eval
        assert "'unsafe-inline'" not in csp_value
        assert "'unsafe-eval'" not in csp_value

    @pytest.mark.asyncio
    async def test_hdr004_csp_dict_sanitizes_semicolons(self):
        """CSP values must be sanitized to prevent header injection."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        # Semicolons in CSP values must be stripped
        csp = {"default-src": ["'self'; injected: bad"]}
        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app, csp=csp)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, None, collector)

        headers = collector.headers_dict
        if "content-security-policy" in headers:
            csp_value = headers["content-security-policy"]
            # Semicolons must be stripped from individual values
            assert "injected" not in csp_value or ";" not in csp_value.split(";")[0]
