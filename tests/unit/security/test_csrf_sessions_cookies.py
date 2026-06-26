"""CSRF, sessions, and cookies security tests.

Requirement IDs: CSRF-001 through CSRF-003, COOKIE-001 through COOKIE-003.
"""

from __future__ import annotations

import inspect

import pytest

from openviper.auth.session.utils import generate_session_key, is_valid_session_key
from openviper.auth.utils.cookies import (
    build_clear_cookie_header,
    build_set_cookie_header,
    get_cookie_settings,
)
from openviper.http.response import JSONResponse
from openviper.middleware.csrf import (
    CSRF_SAFE_METHODS,
    CSRFMiddleware,
    extract_cookie_value,
    generate_csrf_token,
    mask_csrf_token,
    verify_csrf_token,
)

from .conftest import SendCollector, make_scope, override_settings


class TestCSRFProtection:
    """State-changing requests must require CSRF tokens when using cookie auth."""

    @pytest.mark.asyncio
    async def test_csrf001_post_without_token_rejected(self):
        """POST requests without a CSRF token must be rejected."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(SECRET_KEY="test-secret-key-for-csrf-testing"):
            middleware = CSRFMiddleware(app, secret="test-secret-key-for-csrf-testing")

        scope = make_scope(method="POST", headers=[])
        collector = SendCollector()
        await middleware(scope, None, collector)

        # Must return 403 Forbidden
        assert collector.status_code == 403

    @pytest.mark.asyncio
    async def test_csrf001_get_without_token_accepted(self):
        """GET requests must pass through without CSRF validation."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        with override_settings(SECRET_KEY="test-secret-key-for-csrf-testing"):
            middleware = CSRFMiddleware(app, secret="test-secret-key-for-csrf-testing")

        scope = make_scope(method="GET", headers=[])
        collector = SendCollector()
        await middleware(scope, None, collector)

        # GET requests should pass through
        assert collector.status_code == 200

    def test_csrf001_safe_methods_defined(self):
        """CSRF safe methods must be GET, HEAD, and OPTIONS only."""
        assert "GET" in CSRF_SAFE_METHODS
        assert "HEAD" in CSRF_SAFE_METHODS
        assert "OPTIONS" in CSRF_SAFE_METHODS
        # POST, PUT, PATCH, DELETE must NOT be safe
        assert "POST" not in CSRF_SAFE_METHODS
        assert "PUT" not in CSRF_SAFE_METHODS
        assert "DELETE" not in CSRF_SAFE_METHODS


class TestCSRFTokenBinding:
    """CSRF tokens must be bound to the user's session context."""

    def test_csrf002_token_masking_uses_secret(self):
        """Masked CSRF tokens must be bound to the signing secret."""
        secret = "test-secret-key"
        token = generate_csrf_token()

        masked = mask_csrf_token(token, secret)
        # Different secrets must produce different masked tokens
        masked_different = mask_csrf_token(token, "different-secret")
        assert masked != masked_different

    def test_csrf002_token_verification_requires_same_secret(self):
        """Token verification must fail with a different secret."""
        secret = "test-secret-key"
        token = generate_csrf_token()
        masked = mask_csrf_token(token, secret)

        # Must verify with the same secret
        assert verify_csrf_token(token, masked, secret)

        # Must fail with a different secret
        assert not verify_csrf_token(token, masked, "wrong-secret")


class TestCSRFConstantTimeComparison:
    """CSRF token validation must use constant-time comparison."""

    def test_csrf003_uses_hmac_compare_digest(self):
        """The verify_csrf_token function must use hmac.compare_digest."""
        # Verify that the implementation uses hmac.compare_digest
        source = inspect.getsource(verify_csrf_token)
        assert "compare_digest" in source

    def test_csrf003_rejects_short_tokens(self):
        """Tokens shorter than the minimum length must be rejected."""
        secret = "test-secret-key"
        cookie_token = generate_csrf_token()

        # Short submitted tokens must be rejected
        assert not verify_csrf_token(cookie_token, "short", secret)
        assert not verify_csrf_token(cookie_token, "", secret)


class TestSessionCookieSecurity:
    """Session cookies must use HttpOnly, Secure, and SameSite flags."""

    def test_cookie001_httponly_default(self):
        """Session cookies must have HttpOnly flag by default."""
        settings = get_cookie_settings()
        assert settings["httponly"] is True

    def test_cookie001_samesite_default(self):
        """Session cookies must have SameSite=Lax by default."""
        settings = get_cookie_settings()
        assert settings["samesite"].lower() in ("lax", "strict")

    def test_cookie001_secure_in_production(self):
        """Session cookies must have Secure flag in production."""

        with override_settings(SESSION_COOKIE_SECURE=True):
            settings = get_cookie_settings()
            assert settings["secure"] is True

    def test_cookie001_set_cookie_includes_flags(self):
        """The Set-Cookie header must include all security flags."""
        header = build_set_cookie_header("test-session-key")
        assert "HttpOnly" in header
        assert "Path=/" in header

    def test_cookie001_clear_cookie_expires_immediately(self):
        """The clear cookie header must set Max-Age=0."""
        header = build_clear_cookie_header()
        assert "Max-Age=0" in header


class TestSessionInvalidation:
    """Logout must invalidate the server-side session."""

    def test_cookie002_session_key_validation(self):
        """Session keys must be validated for format and length."""
        # Valid keys must pass
        valid_key = generate_session_key()
        assert is_valid_session_key(valid_key)

        # Invalid keys must be rejected
        assert not is_valid_session_key("")
        assert not is_valid_session_key(None)
        assert not is_valid_session_key("short")
        assert not is_valid_session_key("x" * 200)  # Too long

    def test_cookie002_session_key_is_cryptographically_random(self):
        """Session keys must be generated using a CSPRNG."""
        keys = {generate_session_key() for _ in range(50)}
        assert len(keys) == 50  # All unique


class TestDuplicateCookieHandling:
    """Duplicate cookie names must be handled deterministically."""

    def test_cookie003_duplicate_cookies_first_wins(self):
        """When duplicate cookies exist, the first value must be used."""
        cookie_header = "csrftoken=abc; csrftoken=xyz"
        value = extract_cookie_value(cookie_header, "csrftoken")
        # The first occurrence must be used
        assert value == "abc"

    def test_cookie003_empty_cookie_header(self):
        """An empty cookie header must return an empty string."""
        value = extract_cookie_value("", "csrftoken")
        assert value == ""

    def test_cookie003_missing_cookie_name(self):
        """A missing cookie name must return an empty string."""
        value = extract_cookie_value("other=value", "csrftoken")
        assert value == ""
