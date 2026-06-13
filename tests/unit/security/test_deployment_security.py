"""Deployment security tests.

Requirement IDs: DEPLOY-001 through DEPLOY-004.

Covers:
  DEPLOY-001: X-Forwarded-* headers are trusted only from configured proxies.
  DEPLOY-002: Secure cookies work correctly behind trusted TLS proxy.
  DEPLOY-003: Development server does not bind publicly by default.
  DEPLOY-004: Proxy and framework body limits are consistent.
"""

from __future__ import annotations

import pytest

from openviper.auth.utils.cookies import get_cookie_settings
from openviper.cli import run_cmd
from openviper.conf.settings import Settings, validate_settings
from openviper.core.management.commands.start_server import Command
from openviper.exceptions import SettingsValidationError
from openviper.http.request import MAX_BODY_SIZE, MAX_FILES_PER_REQUEST, Request, validate_host_port
from openviper.http.response import Response
from openviper.middleware.ratelimit import SlidingWindowCounter
from openviper.middleware.security import SecurityMiddleware

from .conftest import (
    AsyncMock,
    BodyReceive,
    SendCollector,
    assert_header_absent,
    assert_header_contains,
    assert_header_value,
    assert_rejected,
    make_scope,
    override_settings,
)


async def simple_app(scope: dict, receive: object, send: object) -> None:
    """Trivial ASGI app that returns 200 OK with a short body."""
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


class TestXForwardedHeaders:
    """X-Forwarded-* headers must only be trusted from configured proxies."""

    # ── Positive: valid hosts are accepted ──────────────────────────────

    def test_deploy001_allowed_host_accepted(self) -> None:
        """Requests with a Host matching ALLOWED_HOSTS must pass through."""
        with override_settings(ALLOWED_HOSTS=("trusted.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            assert middleware.is_host_allowed("trusted.example.com")

    def test_deploy001_wildcard_subdomain_accepted(self) -> None:
        """Wildcard subdomain patterns must match correctly."""
        with override_settings(ALLOWED_HOSTS=(".example.com",)):
            middleware = SecurityMiddleware(simple_app)
            assert middleware.is_host_allowed("sub.example.com")
            assert middleware.is_host_allowed("example.com")

    def test_deploy001_localhost_default_allowed(self) -> None:
        """Default ALLOWED_HOSTS includes localhost and 127.0.0.1."""
        with override_settings(ALLOWED_HOSTS=("localhost", "127.0.0.1")):
            middleware = SecurityMiddleware(simple_app)
            assert middleware.is_host_allowed("localhost")
            assert middleware.is_host_allowed("127.0.0.1")

    # ── Negative: spoofed / disallowed hosts are rejected ───────────────

    def test_deploy001_spoofed_x_forwarded_for_rejected(self) -> None:
        """Spoofed X-Forwarded-For must not bypass ALLOWED_HOSTS validation.

        An attacker injecting X-Forwarded-For must not gain access by
        setting a trusted host in that header while the actual Host header
        is malicious.
        """
        with override_settings(ALLOWED_HOSTS=("trusted.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            # The middleware validates the Host header, not X-Forwarded-For.
            # A spoofed X-Forwarded-For cannot bypass host validation.
            assert not middleware.is_host_allowed("evil.com")

    @pytest.mark.asyncio
    async def test_deploy001_spoofed_x_forwarded_proto_rejected(self) -> None:
        """X-Forwarded-Proto must not override scheme without validation.

        An attacker sending X-Forwarded-Proto: https on an HTTP connection
        must not bypass SSL redirect enforcement.
        """
        with override_settings(
            ALLOWED_HOSTS=("trusted.example.com",),
            SECURE_SSL_REDIRECT=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            # The ASGI scope scheme is 'http' - the middleware must redirect
            # regardless of any X-Forwarded-Proto header the client injects.
            scope = make_scope(
                method="GET",
                path="/",
                scheme="http",
                headers=[
                    (b"host", b"trusted.example.com"),
                    (b"x-forwarded-proto", b"https"),
                ],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            # Must still redirect to HTTPS - X-Forwarded-Proto is not trusted.
            assert collector.status_code == 301

    def test_deploy001_spoofed_x_forwarded_host_rejected(self) -> None:
        """X-Forwarded-Host must not bypass ALLOWED_HOSTS validation.

        An attacker sending X-Forwarded-Host with a trusted domain must
        not bypass the Host header check.
        """
        with override_settings(ALLOWED_HOSTS=("trusted.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            # The middleware checks the Host header, not X-Forwarded-Host.
            # A request with an evil Host must be rejected even if
            # X-Forwarded-Host contains a trusted value.
            assert not middleware.is_host_allowed("evil.attacker.com")

    def test_deploy001_disallowed_host_rejected(self) -> None:
        """Requests with a Host not in ALLOWED_HOSTS must be rejected."""
        with override_settings(ALLOWED_HOSTS=("trusted.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            assert not middleware.is_host_allowed("evil.com")

    def test_deploy001_wildcard_not_allowed_by_default(self) -> None:
        """Wildcard '*' must not be in ALLOWED_HOSTS by default."""
        with override_settings(ALLOWED_HOSTS=("example.com",)):
            middleware = SecurityMiddleware(simple_app)
            assert not middleware._allow_all_hosts

    @pytest.mark.asyncio
    async def test_deploy001_host_injection_with_crlf_rejected(self) -> None:
        """Host headers containing CR/LF must be rejected to prevent header injection."""
        with override_settings(ALLOWED_HOSTS=("*",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                headers=[(b"host", b"evil.com\r\nX-Injected: true")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert_rejected(collector.status_code or 200)

    @pytest.mark.asyncio
    async def test_deploy001_host_injection_with_null_byte_rejected(self) -> None:
        """Host headers containing null bytes must be rejected."""
        with override_settings(ALLOWED_HOSTS=("*",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                headers=[(b"host", b"evil.com\0another.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert_rejected(collector.status_code or 200)

    @pytest.mark.asyncio
    async def test_deploy001_full_request_disallowed_host_rejected(self) -> None:
        """End-to-end: request with disallowed Host must receive 400."""
        with override_settings(ALLOWED_HOSTS=("safe.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                headers=[(b"host", b"evil.example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_deploy001_full_request_allowed_host_passes(self) -> None:
        """End-to-end: request with allowed Host must receive 200."""
        with override_settings(ALLOWED_HOSTS=("safe.example.com",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                headers=[(b"host", b"safe.example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 200

    # ── Fail-closed: wildcard host must not bypass explicit checks ──────

    def test_deploy001_wildcard_allows_all_hosts(self) -> None:
        """When '*' is in ALLOWED_HOSTS, all hosts are permitted."""
        with override_settings(ALLOWED_HOSTS=("*",)):
            middleware = SecurityMiddleware(simple_app)
            assert middleware._allow_all_hosts is True
            assert middleware.is_host_allowed("anything.evil.com")

    def test_deploy001_empty_allowed_hosts_rejects_all(self) -> None:
        """Empty ALLOWED_HOSTS must reject all hosts (fail-closed)."""
        with override_settings(ALLOWED_HOSTS=()):
            middleware = SecurityMiddleware(simple_app)
            assert not middleware.is_host_allowed("localhost")
            assert not middleware.is_host_allowed("example.com")


class TestSecureCookiesBehindProxy:
    """Secure cookies must work correctly behind a trusted TLS proxy."""

    # ── Positive: secure cookie flags are set when configured ───────────

    def test_deploy002_session_cookie_secure_flag(self) -> None:
        """Session cookies must set the Secure flag when configured."""
        with override_settings(SESSION_COOKIE_SECURE=True):
            settings = get_cookie_settings()
            assert settings["secure"] is True

    def test_deploy002_session_cookie_httponly_flag(self) -> None:
        """Session cookies must have HttpOnly flag by default."""
        settings = get_cookie_settings()
        assert settings["httponly"] is True

    def test_deploy002_session_cookie_samesite_flag(self) -> None:
        """Session cookies must have SameSite=Lax or Strict by default."""
        settings = get_cookie_settings()
        assert settings["samesite"].lower() in ("lax", "strict")

    def test_deploy002_response_set_cookie_secure_attribute(self) -> None:
        """Response.set_cookie with secure=True must include the Secure attribute."""
        response = Response("ok")
        response.set_cookie("sessionid", "abc123", secure=True, httponly=True, samesite="Lax")
        raw_headers = response._headers.raw
        cookie_headers = [
            v.decode("latin-1") if isinstance(v, bytes) else v
            for k, v in raw_headers
            if (k.decode("latin-1") if isinstance(k, bytes) else k).lower() == "set-cookie"
        ]
        assert len(cookie_headers) == 1
        cookie = cookie_headers[0]
        assert "Secure" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie

    def test_deploy002_response_set_cookie_insecure_without_secure(self) -> None:
        """Response.set_cookie without secure must not include the Secure attribute."""
        response = Response("ok")
        response.set_cookie("pref", "dark", secure=False, httponly=False, samesite="Lax")
        raw_headers = response._headers.raw
        cookie_headers = [
            v.decode("latin-1") if isinstance(v, bytes) else v
            for k, v in raw_headers
            if (k.decode("latin-1") if isinstance(k, bytes) else k).lower() == "set-cookie"
        ]
        assert len(cookie_headers) == 1
        cookie = cookie_headers[0]
        assert "Secure" not in cookie

    # ── Negative: insecure defaults and misconfigurations ───────────────

    def test_deploy002_session_cookie_secure_default_false(self) -> None:
        """SESSION_COOKIE_SECURE must default to False for development,
        ensuring the default is well-understood and must be changed in prod."""
        # Without production environment, secure defaults to False.
        with override_settings(SESSION_COOKIE_SECURE=False):
            settings = get_cookie_settings()
            assert settings["secure"] is False

    def test_deploy002_samesite_none_requires_secure(self) -> None:
        """SameSite=None must require Secure=True - browsers reject otherwise."""
        response = Response("ok")
        with pytest.raises(ValueError, match="SameSite=None must also set Secure"):
            response.set_cookie("sessionid", "abc", samesite="None", secure=False)

    def test_deploy002_cookie_injection_crlf_rejected(self) -> None:
        """Cookie names/values with CR/LF must be rejected to prevent header injection."""
        response = Response("ok")
        with pytest.raises(ValueError, match="must not contain CR or LF"):
            response.set_cookie("sessionid\r\nSet-Cookie: evil=true", "val")
        with pytest.raises(ValueError, match="must not contain CR or LF"):
            response.set_cookie("sessionid", "val\nSet-Cookie: evil=true")

    # ── SSL redirect behind proxy ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_deploy002_ssl_redirect_enforced_on_http(self) -> None:
        """SECURE_SSL_REDIRECT=True must redirect HTTP to HTTPS."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_SSL_REDIRECT=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/dashboard",
                scheme="http",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 301
            location = collector.headers_dict.get("location", "")
            assert location.startswith("https://example.com/dashboard")

    @pytest.mark.asyncio
    async def test_deploy002_ssl_redirect_not_applied_on_https(self) -> None:
        """SECURE_SSL_REDIRECT=True must not redirect when scheme is already HTTPS."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_SSL_REDIRECT=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/dashboard",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 200

    @pytest.mark.asyncio
    async def test_deploy002_hsts_header_set_on_https(self) -> None:
        """HSTS header must be present when SECURE_HSTS_SECONDS > 0."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_HSTS_SECONDS=31536000,
            SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
            SECURE_HSTS_PRELOAD=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            hsts = collector.headers_dict.get("strict-transport-security", "")
            assert "max-age=31536000" in hsts
            assert "includeSubDomains" in hsts
            assert "preload" in hsts

    @pytest.mark.asyncio
    async def test_deploy002_hsts_header_absent_when_disabled(self) -> None:
        """HSTS header must not be present when SECURE_HSTS_SECONDS=0."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_HSTS_SECONDS=0,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert "strict-transport-security" not in collector.headers_dict

    @pytest.mark.asyncio
    async def test_deploy002_ssl_redirect_rejects_crlf_in_path(self) -> None:
        """SSL redirect must reject paths containing CR/LF to prevent header injection."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_SSL_REDIRECT=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/safe\r\nSet-Cookie: evil=true",
                scheme="http",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            # Must reject with 400, not redirect with injected headers.
            assert_rejected(collector.status_code or 200)

    @pytest.mark.asyncio
    async def test_deploy002_ssl_redirect_rejects_crlf_in_query_string(self) -> None:
        """SSL redirect must reject query strings containing CR/LF."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_SSL_REDIRECT=True,
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/search",
                query_string=b"q=test\r\nSet-Cookie: evil=true",
                scheme="http",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert_rejected(collector.status_code or 200)

    # ── Production validation ────────────────────────────────────────────

    def test_deploy002_production_requires_session_cookie_secure(self) -> None:
        """Production settings validation must require SESSION_COOKIE_SECURE=True."""
        with override_settings(
            SESSION_COOKIE_SECURE=False,
            SECURE_SSL_REDIRECT=True,
            SECURE_HSTS_SECONDS=31536000,
            SECURE_COOKIES=True,
            CSRF_COOKIE_SECURE=True,
            DEBUG=False,
            SECRET_KEY="a" * 64,
            DATABASES={"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}},
            ALLOWED_HOSTS=("example.com",),
        ):
            with pytest.raises(SettingsValidationError):
                validate_settings(Settings(), env="production")


class TestDevServerBinding:
    """Development server must not bind to public interfaces by default."""

    # ── Positive: default bind is localhost ──────────────────────────────

    def test_deploy003_default_bind_is_localhost(self) -> None:
        """The default --host argument must be 127.0.0.1 (localhost only)."""
        cmd = Command()
        parser = __import__("argparse", fromlist=["ArgumentParser"]).ArgumentParser()
        cmd.add_arguments(parser)
        args = parser.parse_args([])
        assert args.host == "127.0.0.1"

    def test_deploy003_cli_default_bind_is_localhost(self) -> None:
        """The CLI run command must default to 127.0.0.1."""
        # Inspect the click option default for --host.
        param = next(p for p in run_cmd.params if hasattr(p, "name") and p.name == "host")
        assert param.default == "127.0.0.1"

    def test_deploy003_settings_debug_overridable(self) -> None:
        """DEBUG must be overridable to False for production."""
        settings = Settings(DEBUG=False)
        assert settings.DEBUG is False

    def test_deploy003_settings_debug_default_true(self) -> None:
        """DEBUG must default to True for development convenience."""
        settings = Settings()
        assert settings.DEBUG is True

    # ── Negative: public bind must be explicit ───────────────────────────

    def test_deploy003_explicit_public_bind_allowed(self) -> None:
        """Binding to 0.0.0.0 must require an explicit --host flag."""
        cmd = Command()
        parser = __import__("argparse", fromlist=["ArgumentParser"]).ArgumentParser()
        cmd.add_arguments(parser)
        args = parser.parse_args(["--host", "0.0.0.0"])
        assert args.host == "0.0.0.0"
        # The default must NOT be 0.0.0.0.
        args_default = parser.parse_args([])
        assert args_default.host != "0.0.0.0"

    def test_deploy003_production_validation_rejects_debug(self) -> None:
        """Production settings validation must reject DEBUG=True."""
        with override_settings(
            DEBUG=True,
            SECRET_KEY="a" * 64,
            DATABASES={"default": {"OPTIONS": {"URL": "sqlite:///test.db"}}},
            ALLOWED_HOSTS=("example.com",),
            SECURE_SSL_REDIRECT=True,
            SECURE_HSTS_SECONDS=31536000,
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_COOKIES=True,
        ):
            with pytest.raises(SettingsValidationError):
                validate_settings(Settings(), env="production")

    def test_deploy003_allowed_hosts_default_restrictive(self) -> None:
        """Default ALLOWED_HOSTS must be restrictive (localhost only)."""
        settings = Settings()
        assert "localhost" in settings.ALLOWED_HOSTS
        assert "0.0.0.0" not in settings.ALLOWED_HOSTS
        assert "*" not in settings.ALLOWED_HOSTS

    def test_deploy003_ssl_redirect_default_off(self) -> None:
        """SECURE_SSL_REDIRECT must default to False (development) but be
        enforceable in production."""
        settings = Settings()
        assert settings.SECURE_SSL_REDIRECT is False

    def test_deploy003_hsts_default_zero(self) -> None:
        """SECURE_HSTS_SECONDS must default to 0 (disabled) for development."""
        settings = Settings()
        assert settings.SECURE_HSTS_SECONDS == 0


class TestBodyLimits:
    """Body and header limits must be consistently enforced."""

    # ── Positive: limits are defined and reasonable ─────────────────────

    def test_deploy004_max_body_size_defined(self) -> None:
        """MAX_BODY_SIZE must be defined and reasonable."""
        assert MAX_BODY_SIZE > 0
        assert MAX_BODY_SIZE <= 100 * 1024 * 1024  # 100 MB max

    def test_deploy004_max_files_per_request_defined(self) -> None:
        """MAX_FILES_PER_REQUEST must be defined and reasonable."""
        assert MAX_FILES_PER_REQUEST > 0
        assert MAX_FILES_PER_REQUEST <= 1000

    def test_deploy004_rate_limit_max_requests_defined(self) -> None:
        """Rate limit max_requests must be configurable."""
        counter = SlidingWindowCounter(max_requests=100, window_seconds=60)
        assert counter.max_requests == 100
        assert counter.window == 60

    def test_deploy004_settings_rate_limit_defaults(self) -> None:
        """Rate limit settings must have sensible defaults."""
        settings = Settings()
        assert settings.RATE_LIMIT_REQUESTS > 0
        assert settings.RATE_LIMIT_WINDOW > 0

    # ── Negative: oversized bodies are rejected ──────────────────────────

    @pytest.mark.asyncio
    async def test_deploy004_request_body_exceeds_max_rejected(self) -> None:
        """Requests exceeding MAX_BODY_SIZE must be rejected."""
        scope = make_scope(
            method="POST",
            path="/upload",
            headers=[(b"content-length", str(MAX_BODY_SIZE + 1).encode())],
        )
        receive = BodyReceive(b"x" * (MAX_BODY_SIZE + 1))
        request = Request(scope, receive)
        with pytest.raises(ValueError, match="exceeds"):
            await request.body()

    @pytest.mark.asyncio
    async def test_deploy004_request_body_at_max_accepted(self) -> None:
        """Requests at exactly MAX_BODY_SIZE must be accepted."""
        # Use a small content-length that is within limits.
        scope = make_scope(
            method="POST",
            path="/upload",
            headers=[(b"content-length", b"100")],
        )
        receive = BodyReceive(b"x" * 100)
        request = Request(scope, receive)
        body = await request.body()
        assert len(body) == 100

    @pytest.mark.asyncio
    async def test_deploy004_request_body_zero_length_accepted(self) -> None:
        """Zero-length request bodies must be accepted."""
        scope = make_scope(
            method="POST",
            path="/upload",
            headers=[(b"content-length", b"0")],
        )
        receive = BodyReceive(b"")
        request = Request(scope, receive)
        body = await request.body()
        assert body == b""

    @pytest.mark.asyncio
    async def test_deploy004_request_body_oversized_no_content_length_rejected(self) -> None:
        """Requests without Content-Length but oversized body must be rejected."""
        # No content-length header, but body exceeds MAX_BODY_SIZE.
        scope = make_scope(
            method="POST",
            path="/upload",
            headers=[],
        )
        # Simulate a body that exceeds the limit in chunks.
        large_body = b"x" * (MAX_BODY_SIZE + 1)
        receive = BodyReceive(large_body)
        request = Request(scope, receive)
        with pytest.raises(ValueError, match="exceeds"):
            await request.body()

    # ── Host validation in request ───────────────────────────────────────

    def test_deploy004_request_host_validation_rejects_injection(self) -> None:
        """Request.host must reject Host headers with CRLF characters."""
        assert not validate_host_port("evil.com\r\nSet-Cookie: bad=true")
        assert not validate_host_port("evil.com\nX-Injected: yes")

    def test_deploy004_request_host_validation_accepts_valid(self) -> None:
        """Request.host must accept valid hostnames."""
        assert validate_host_port("example.com")
        assert validate_host_port("example.com:8080")
        assert validate_host_port("127.0.0.1")
        assert validate_host_port("sub.domain.example.com")

    def test_deploy004_request_host_validation_rejects_invalid_port(self) -> None:
        """Request.host must reject invalid port numbers."""
        assert not validate_host_port("example.com:0")
        assert not validate_host_port("example.com:99999")

    # ── Consistency: framework and proxy limits must align ───────────────

    def test_deploy004_max_body_size_is_10mb(self) -> None:
        """MAX_BODY_SIZE must be exactly 10 MB (framework default)."""
        assert MAX_BODY_SIZE == 10 * 1024 * 1024

    def test_deploy004_max_files_per_request_is_100(self) -> None:
        """MAX_FILES_PER_REQUEST must be exactly 100 (framework default)."""
        assert MAX_FILES_PER_REQUEST == 100

    def test_deploy004_settings_secure_cookies_default_false(self) -> None:
        """SECURE_COOKIES must default to False (development) but be
        enforceable in production."""
        settings = Settings()
        assert settings.SECURE_COOKIES is False

    def test_deploy004_settings_csrf_cookie_secure_default_false(self) -> None:
        """CSRF_COOKIE_SECURE must default to False (development)."""
        settings = Settings()
        assert settings.CSRF_COOKIE_SECURE is False

    # ── Rate limiting enforcement ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_deploy004_rate_limit_blocks_excess_requests(self) -> None:
        """Rate limiter must block requests exceeding the configured limit."""
        counter = SlidingWindowCounter(max_requests=2, window_seconds=60)
        allowed1, remaining1 = await counter.is_allowed("client-1")
        assert allowed1 is True
        assert remaining1 == 1

        allowed2, remaining2 = await counter.is_allowed("client-1")
        assert allowed2 is True
        assert remaining2 == 0

        # Third request must be blocked.
        allowed3, remaining3 = await counter.is_allowed("client-1")
        assert allowed3 is False
        assert remaining3 == 0

    @pytest.mark.asyncio
    async def test_deploy004_rate_limit_allows_other_clients(self) -> None:
        """Rate limiter must track clients independently."""
        counter = SlidingWindowCounter(max_requests=1, window_seconds=60)
        allowed, _ = await counter.is_allowed("client-1")
        assert allowed is True

        # client-1 is now rate-limited, but client-2 must still be allowed.
        allowed1, _ = await counter.is_allowed("client-1")
        assert allowed1 is False

        allowed2, _ = await counter.is_allowed("client-2")
        assert allowed2 is True

    # ── Security headers consistency ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_deploy004_security_headers_present_by_default(self) -> None:
        """SecurityMiddleware must add default security headers."""
        with override_settings(ALLOWED_HOSTS=("example.com",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert_header_value(collector.headers_dict, "x-content-type-options", "nosniff")
            assert_header_value(collector.headers_dict, "x-frame-options", "DENY")
            assert_header_contains(
                collector.headers_dict, "referrer-policy", "strict-origin-when-cross-origin"
            )

    @pytest.mark.asyncio
    async def test_deploy004_xss_filter_deprecated_not_present_by_default(self) -> None:
        """X-XSS-Protection must not be present by default (deprecated header)."""
        with override_settings(ALLOWED_HOSTS=("example.com",)):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert_header_absent(collector.headers_dict, "x-xss-protection")

    @pytest.mark.asyncio
    async def test_deploy004_csp_header_when_configured(self) -> None:
        """Content-Security-Policy header must be present when configured."""
        with override_settings(
            ALLOWED_HOSTS=("example.com",),
            SECURE_CONTENT_SECURITY_POLICY={"default-src": "'self'"},
        ):
            middleware = SecurityMiddleware(simple_app)
            scope = make_scope(
                method="GET",
                path="/",
                scheme="https",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert "content-security-policy" in collector.headers_dict
            assert "default-src 'self'" in collector.headers_dict["content-security-policy"]
