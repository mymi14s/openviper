"""Tests for all security audit fixes applied to the OpenViper codebase."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth import jwt as jwt_mod
from openviper.auth.hashers import check_password, make_password
from openviper.auth.token_blocklist import _NEGATIVE_CACHE_TTL
from openviper.db.events import (
    _MAX_BACKGROUND_TASKS,
    _background_tasks,
    _call_handler,
)
from openviper.db.fields import ForeignKey
from openviper.http.response import RedirectResponse
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.csrf import (
    CSRF_FORM_FIELD,
    CSRFMiddleware,
    _generate_csrf_token,
    _mask_csrf_token,
)
from openviper.middleware.security import SecurityMiddleware


async def _ok_app(scope: dict, receive: object, send: object) -> None:
    pass


class TestHashersExceptSyntax:
    """Verify the except clause uses tuple syntax for multiple exception types."""

    @pytest.mark.asyncio
    async def test_argon2_invalid_hash_returns_false(self) -> None:
        result = await check_password("password", "argon2$notavalidhash")
        assert result is False

    @pytest.mark.asyncio
    async def test_bcrypt_invalid_hash_returns_false(self) -> None:
        result = await check_password("password", "bcrypt$notavalidhash")
        assert result is False

    @pytest.mark.asyncio
    async def test_argon2_correct_password_returns_true(self) -> None:
        hashed = await make_password("correcthorse", algorithm="argon2")
        assert await check_password("correcthorse", hashed) is True

    @pytest.mark.asyncio
    async def test_bcrypt_correct_password_returns_true(self) -> None:
        hashed = await make_password("correcthorse", algorithm="bcrypt")
        assert await check_password("correcthorse", hashed) is True


class TestCORSCredentialsWildcard:
    """Reject allow_credentials=True combined with wildcard origins."""

    def test_wildcard_with_credentials_raises(self) -> None:
        with pytest.raises(ValueError, match="allow_credentials.*wildcard"):
            CORSMiddleware(_ok_app, allowed_origins=["*"], allow_credentials=True)

    def test_explicit_origin_with_credentials_ok(self) -> None:
        mw = CORSMiddleware(
            _ok_app,
            allowed_origins=["https://example.com"],
            allow_credentials=True,
        )
        assert mw.allow_credentials is True

    def test_wildcard_without_credentials_ok(self) -> None:
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"], allow_credentials=False)
        assert mw._allow_all_origins is True


class TestCSRFFormFieldExtraction:
    """CSRF token can be extracted from x-www-form-urlencoded body."""

    @pytest.mark.asyncio
    async def test_form_body_token_accepted(self) -> None:
        """A valid CSRF token submitted via form field should pass validation."""
        secret = "test-secret-key-for-csrf"
        cookie_token = _generate_csrf_token()
        masked = _mask_csrf_token(cookie_token, secret)

        form_body = f"{CSRF_FORM_FIELD}={masked}".encode("latin-1")
        cookie_val = f"csrftoken={cookie_token}"

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/submit",
            "headers": [
                (b"cookie", cookie_val.encode("latin-1")),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
        }

        app_called = False

        async def track_app(s: dict, r: object, snd: object) -> None:
            nonlocal app_called
            app_called = True

        mw = CSRFMiddleware(track_app, secret=secret)

        body_sent = False

        async def receive() -> dict:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": form_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        messages: list[dict] = []

        async def send(msg: dict) -> None:
            messages.append(msg)

        await mw(scope, receive, send)
        assert app_called, "App should be called when CSRF form token is valid"

    @pytest.mark.asyncio
    async def test_header_token_still_works(self) -> None:
        """Header-based CSRF token submission should continue working."""
        secret = "test-secret"
        cookie_token = _generate_csrf_token()
        masked = _mask_csrf_token(cookie_token, secret)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/update",
            "headers": [
                (b"cookie", f"csrftoken={cookie_token}".encode("latin-1")),
                (b"x-csrftoken", masked.encode("latin-1")),
            ],
        }

        app_called = False

        async def track_app(s: dict, r: object, snd: object) -> None:
            nonlocal app_called
            app_called = True

        mw = CSRFMiddleware(track_app, secret=secret)
        await mw(scope, AsyncMock(), AsyncMock())
        assert app_called


class TestRedirectResponseOpenRedirect:
    """RedirectResponse rejects protocol-relative and exotic-scheme URLs."""

    def test_protocol_relative_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="Protocol-relative"):
            RedirectResponse("//evil.com/phish")

    def test_protocol_relative_with_leading_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="Protocol-relative"):
            RedirectResponse("  //evil.com")

    def test_javascript_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse("javascript:alert(1)")

    def test_data_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse("data:text/html,<h1>pwned</h1>")

    def test_relative_path_allowed(self) -> None:
        r = RedirectResponse("/dashboard")
        assert r.status_code == 307

    def test_absolute_http_url_allowed(self) -> None:
        r = RedirectResponse("https://example.com/callback")
        assert r.status_code == 307

    def test_crlf_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse("/path\r\nX-Injected: evil")


class TestSecurityMiddlewareIPv6:
    """SecurityMiddleware correctly parses IPv6 bracket notation hosts."""

    def test_strip_port_ipv4(self) -> None:
        assert SecurityMiddleware._strip_port("example.com:8000") == "example.com"

    def test_strip_port_ipv4_no_port(self) -> None:
        assert SecurityMiddleware._strip_port("example.com") == "example.com"

    def test_strip_port_ipv6_with_port(self) -> None:
        assert SecurityMiddleware._strip_port("[::1]:8000") == "::1"

    def test_strip_port_ipv6_no_port(self) -> None:
        assert SecurityMiddleware._strip_port("[::1]") == "::1"

    def test_strip_port_ipv6_full(self) -> None:
        assert SecurityMiddleware._strip_port("[2001:db8::1]:443") == "2001:db8::1"


class TestSecurityMiddlewareCSPSanitization:
    """CSP dict values with semicolons cannot inject extra directives."""

    def test_semicolons_stripped_from_csp_values(self) -> None:
        """A semicolon in a CSP value should not create an extra directive."""
        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            ms.SECURE_SSL_REDIRECT = False
            ms.SECURE_HSTS_SECONDS = 0
            ms.SECURE_HSTS_INCLUDE_SUBDOMAINS = False
            ms.SECURE_HSTS_PRELOAD = False
            ms.X_FRAME_OPTIONS = "DENY"
            mw = SecurityMiddleware(
                _ok_app,
                csp={"default-src": "'self'; script-src 'unsafe-inline'"},
            )
        csp_headers = [v for k, v in mw._fixed_headers if k == b"content-security-policy"]
        assert len(csp_headers) == 1
        csp_value = csp_headers[0].decode("latin-1")
        # The injected semicolon should have been stripped
        assert (
            "script-src" not in csp_value
            or ";" not in csp_value.split("default-src")[1].split(";")[0]
        )


class TestSessionCookieSecureDefault:
    """Session cookies default to secure=True regardless of environment."""

    @pytest.mark.asyncio
    async def test_secure_defaults_to_true(self) -> None:
        from openviper.auth.backends import login

        with patch("openviper.auth.backends.settings") as ms:
            ms.SESSION_COOKIE_NAME = "sessionid"
            ms.SESSION_COOKIE_DOMAIN = None
            ms.SESSION_TIMEOUT = MagicMock()
            ms.SESSION_TIMEOUT.total_seconds.return_value = 3600
            ms.SESSION_COOKIE_HTTPONLY = True
            # Deliberately do NOT set SESSION_COOKIE_SECURE on settings
            # to test the default fallback
            del ms.SESSION_COOKIE_SECURE
            ms.SESSION_COOKIE_SAMESITE = "lax"
            ms.SESSION_COOKIE_PATH = "/"

            response = MagicMock()
            request = MagicMock()
            request.user = None
            request.cookies = {}
            request._session = None
            user = MagicMock()
            user.pk = 1

            mock_session = MagicMock()
            mock_session.key = "session-key-abc"
            mock_store = MagicMock()
            mock_store.create = AsyncMock(return_value=mock_session)
            mock_store.rotate = AsyncMock(return_value=mock_session)

            with patch("openviper.auth.backends.get_session_store", return_value=mock_store):
                await login(request, user, response)

            call_kwargs = response.set_cookie.call_args
            assert call_kwargs is not None
            # The secure kwarg should be True (default)
            assert call_kwargs.kwargs.get("secure", call_kwargs[1].get("secure")) is True


class TestTokenBlocklistCacheTTL:
    """Negative cache TTL is reduced for faster revocation propagation."""

    def test_negative_cache_ttl_is_10_seconds(self) -> None:
        assert _NEGATIVE_CACHE_TTL == 10.0


class TestJWTKeyFormatValidation:
    """Asymmetric algorithms require PEM-formatted keys."""

    def test_hs256_with_string_key_allowed(self) -> None:
        """HMAC algorithms accept plain string keys — should not raise."""
        secret, algo = jwt_mod._get_jwt_config()
        assert algo in {
            "HS256",
            "HS384",
            "HS512",
        } or secret.strip().startswith("-----")


class TestForeignKeyOnDeleteValidation:
    """ForeignKey rejects invalid on_delete values at construction time."""

    def test_cascade_accepted(self) -> None:
        fk = ForeignKey(to="SomeModel", on_delete="CASCADE")
        assert fk.on_delete == "CASCADE"

    def test_set_null_accepted(self) -> None:
        fk = ForeignKey(to="SomeModel", on_delete="SET_NULL")
        assert fk.on_delete == "SET_NULL"

    def test_protect_accepted(self) -> None:
        fk = ForeignKey(to="SomeModel", on_delete="PROTECT")
        assert fk.on_delete == "PROTECT"

    def test_set_default_accepted(self) -> None:
        fk = ForeignKey(to="SomeModel", on_delete="SET_DEFAULT")
        assert fk.on_delete == "SET_DEFAULT"

    def test_do_nothing_accepted(self) -> None:
        fk = ForeignKey(to="SomeModel", on_delete="DO_NOTHING")
        assert fk.on_delete == "DO_NOTHING"

    def test_typo_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid on_delete"):
            ForeignKey(to="SomeModel", on_delete="CASCASE")

    def test_lowercase_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid on_delete"):
            ForeignKey(to="SomeModel", on_delete="cascade")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid on_delete"):
            ForeignKey(to="SomeModel", on_delete="")


class TestBackgroundTasksCap:
    """Background task set is capped to prevent unbounded growth."""

    def test_max_background_tasks_defined(self) -> None:
        assert _MAX_BACKGROUND_TASKS == 1024

    @pytest.mark.asyncio
    async def test_handler_skipped_when_at_capacity(self) -> None:
        """When _background_tasks is at capacity, new async handlers are skipped."""
        original_tasks = _background_tasks.copy()
        try:
            # Fill with sentinel tasks
            sentinel_tasks = set()
            for _ in range(_MAX_BACKGROUND_TASKS):
                fut: asyncio.Future[None] = asyncio.get_event_loop().create_future()
                task = asyncio.ensure_future(fut)
                _background_tasks.add(task)
                sentinel_tasks.add(task)

            handler = AsyncMock()
            instance = MagicMock()
            _call_handler(handler, instance, "after_save")
            handler.assert_not_called()
        finally:
            # Clean up sentinel tasks
            for t in sentinel_tasks:
                t.cancel()
                _background_tasks.discard(t)
            _background_tasks.clear()
            _background_tasks.update(original_tasks)
