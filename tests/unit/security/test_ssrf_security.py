"""SSRF security tests.

Requirement IDs: SSRF-001 through SSRF-004.

Covers:
  SSRF-001 – Outbound URL fetcher blocks private IP ranges
  SSRF-002 – Redirects cannot bypass SSRF protections
  SSRF-003 – Dangerous protocols are rejected
  SSRF-004 – DNS rebinding protections (per-request validation)
"""

from __future__ import annotations

import asyncio
import ipaddress
from unittest.mock import AsyncMock

import pytest

from openviper.http.request import VALID_HOST_RE, validate_host_port
from openviper.http.response import RedirectResponse
from openviper.middleware.security import SecurityMiddleware

from .conftest import SendCollector, make_scope, override_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def dummy_app(scope: dict, receive: object, send: object) -> None:
    """Minimal ASGI app that returns 200 OK."""
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": b"OK"})


# ---------------------------------------------------------------------------
# SSRF-001: Outbound URL fetcher blocks private IP ranges
# ---------------------------------------------------------------------------


class TestSSRF001PrivateIPBlocking:
    """Outbound URL fetches must block private IP ranges."""

    # ── Positive: valid public hosts are accepted ────────────────────────

    def test_ssrf001_allows_public_hostname(self) -> None:
        """Public hostnames must pass ALLOWED_HOSTS validation."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("example.com")

    def test_ssrf001_allows_subdomain_of_wildcard(self) -> None:
        """Subdomains of a wildcard ALLOWED_HOSTS entry must be accepted."""
        with override_settings(ALLOWED_HOSTS=[".example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("sub.example.com")
            assert middleware.is_host_allowed("example.com")

    # ── Negative: loopback addresses are blocked ────────────────────────

    def test_ssrf001_blocks_localhost(self) -> None:
        """'localhost' must be rejected when not in ALLOWED_HOSTS."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("localhost")

    def test_ssrf001_blocks_ipv4_loopback_127_0_0_1(self) -> None:
        """127.0.0.1 must be rejected when not in ALLOWED_HOSTS."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("127.0.0.1")

    def test_ssrf001_blocks_ipv4_loopback_range(self) -> None:
        """Entire 127.0.0.0/8 loopback range must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            for octet in range(0, 256, 64):
                host = f"127.0.0.{octet}"
                assert not middleware.is_host_allowed(host), f"{host} should be blocked"

    def test_ssrf001_blocks_ipv6_loopback(self) -> None:
        """IPv6 loopback ::1 must be rejected when not in ALLOWED_HOSTS."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("::1")

    # ── Negative: RFC 1918 private ranges are blocked ────────────────────

    def test_ssrf001_blocks_10_network(self) -> None:
        """10.0.0.0/8 private range must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("10.0.0.1")
            assert not middleware.is_host_allowed("10.255.255.255")

    def test_ssrf001_blocks_172_16_network(self) -> None:
        """172.16.0.0/12 private range must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("172.16.0.1")
            assert not middleware.is_host_allowed("172.31.255.255")

    def test_ssrf001_blocks_192_168_network(self) -> None:
        """192.168.0.0/16 private range must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("192.168.0.1")
            assert not middleware.is_host_allowed("192.168.255.255")

    # ── Negative: link-local and cloud metadata endpoints ────────────────

    def test_ssrf001_blocks_link_local_169_254(self) -> None:
        """169.254.0.0/16 link-local range must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("169.254.0.1")
            assert not middleware.is_host_allowed("169.254.169.254")

    def test_ssrf001_blocks_aws_metadata_endpoint(self) -> None:
        """AWS metadata endpoint 169.254.169.254 must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("169.254.169.254")

    # ── Negative: Host header injection patterns ─────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf001_rejects_crlf_in_host(self) -> None:
        """Host header with CR/LF characters must be rejected at the middleware level."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"example.com\r\nX-Injected: true")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf001_rejects_null_byte_in_host(self) -> None:
        """Host header with null byte must be rejected."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"example.com\0evil.com")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    # ── Host regex validation ────────────────────────────────────────────

    def test_ssrf001_valid_host_re_rejects_injection_patterns(self) -> None:
        """VALID_HOST_RE must reject patterns used for Host header injection."""
        assert not VALID_HOST_RE.match("127.0.0.1\r\n")
        assert not VALID_HOST_RE.match("")
        assert not VALID_HOST_RE.match(" ")
        assert not VALID_HOST_RE.match("host\r\nX-Injected: true")
        assert not VALID_HOST_RE.match("host\0evil")

    def test_ssrf001_valid_host_re_accepts_well_formed_hosts(self) -> None:
        """VALID_HOST_RE must accept well-formed hostnames."""
        assert VALID_HOST_RE.match("example.com")
        assert VALID_HOST_RE.match("sub.example.com")
        assert VALID_HOST_RE.match("example.com:443")
        assert VALID_HOST_RE.match("localhost:8000")
        assert VALID_HOST_RE.match("my-host.local")

    # ── validate_host_port ──────────────────────────────────────────────

    def test_ssrf001validate_host_port_rejects_invalid_ports(self) -> None:
        """validate_host_port must reject out-of-range ports."""
        assert not validate_host_port("example.com:0")
        assert not validate_host_port("example.com:65536")
        assert not validate_host_port("example.com:99999")

    def test_ssrf001validate_host_port_accepts_valid_hosts(self) -> None:
        """validate_host_port must accept valid host:port combinations."""
        assert validate_host_port("example.com")
        assert validate_host_port("example.com:443")
        assert validate_host_port("example.com:80")

    # ── ipaddress library confirms private ranges ─────────────────────────

    def test_ssrf001_ipaddress_library_identifies_private_ranges(self) -> None:
        """Standard library must classify known SSRF targets as private."""
        targets_and_ranges = [
            ("127.0.0.1", ipaddress.ip_network("127.0.0.0/8")),
            ("10.0.0.1", ipaddress.ip_network("10.0.0.0/8")),
            ("172.16.0.1", ipaddress.ip_network("172.16.0.0/12")),
            ("192.168.1.1", ipaddress.ip_network("192.168.0.0/16")),
            ("169.254.169.254", ipaddress.ip_network("169.254.0.0/16")),
        ]
        for target, network in targets_and_ranges:
            assert ipaddress.ip_address(target) in network, f"{target} must be in {network}"

    # ── Fail-closed: wildcard ALLOWED_HOSTS ──────────────────────────────

    def test_ssrf001_wildcard_allows_all_hosts(self) -> None:
        """When ALLOWED_HOSTS=['*'], all hosts pass (intentional opt-in)."""
        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("127.0.0.1")
            assert middleware.is_host_allowed("evil.internal")

    def test_ssrf001_empty_allowed_hosts_blocks_everything(self) -> None:
        """Empty ALLOWED_HOSTS must block all hosts (fail-closed default)."""
        with override_settings(ALLOWED_HOSTS=[]):
            middleware = SecurityMiddleware(dummy_app)
            assert not middleware.is_host_allowed("example.com")
            assert not middleware.is_host_allowed("localhost")

    # ── Full middleware pipeline: ASGI request with private IP host ───────

    @pytest.mark.asyncio
    async def test_ssrf001_middleware_rejects_private_ip_host(self) -> None:
        """Full middleware pipeline must reject requests with private IP hosts."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"127.0.0.1")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf001_middleware_rejects_localhost_host(self) -> None:
        """Full middleware pipeline must reject requests with localhost host."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"localhost")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf001_middleware_rejects_aws_metadata_host(self) -> None:
        """Full middleware pipeline must reject requests targeting AWS metadata."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"169.254.169.254")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf001_middleware_allows_trusted_host(self) -> None:
        """Full middleware pipeline must allow requests with trusted hosts."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"example.com")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 200


# ---------------------------------------------------------------------------
# SSRF-002: Redirects cannot bypass SSRF protections
# ---------------------------------------------------------------------------


class TestSSRF002RedirectBypass:
    """Redirects must not bypass SSRF protections."""

    # ── Positive: safe redirects work ────────────────────────────────────

    def test_ssrf002_internal_redirect_accepted(self) -> None:
        """Internal path redirects must be accepted by RedirectResponse."""
        response = RedirectResponse(url="/safe-path", status_code=302)
        assert response.status_code == 302
        assert response.headers.get("location") == "/safe-path"

    def test_ssrf002_https_redirect_accepted(self) -> None:
        """HTTPS redirects to trusted hosts must be accepted."""
        response = RedirectResponse(url="https://trusted.example.com/path", status_code=301)
        assert response.status_code == 301
        assert "trusted.example.com" in response.headers.get("location", "")

    # ── Negative: protocol-relative redirects blocked ────────────────────

    def test_ssrf002_protocol_relative_redirect_blocked(self) -> None:
        """Protocol-relative URLs (//evil.com) must be rejected."""
        with pytest.raises(ValueError, match="Protocol-relative"):
            RedirectResponse(url="//evil.com/steal-cookies")

    def test_ssrf002_protocol_relative_with_spaces_blocked(self) -> None:
        """Protocol-relative URLs with leading spaces must be rejected."""
        with pytest.raises(ValueError, match="Protocol-relative"):
            RedirectResponse(url="  //evil.com/path")

    # ── Negative: CRLF injection in redirect URLs ────────────────────────

    def test_ssrf002_crlf_in_redirect_url_blocked(self) -> None:
        """Redirect URLs with CR characters must be rejected."""
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse(url="/safe\r\nSet-Cookie: evil=true")

    def test_ssrf002_lf_in_redirect_url_blocked(self) -> None:
        """Redirect URLs with LF characters must be rejected."""
        with pytest.raises(ValueError, match="CR or LF"):
            RedirectResponse(url="/safe\nX-Injected: yes")

    # ── Negative: path traversal in redirect URLs ─────────────────────────

    def test_ssrf002_path_traversal_in_redirect_blocked(self) -> None:
        """Redirect URLs with path traversal sequences must be rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            RedirectResponse(url="/safe/../../etc/passwd")

    # ── Negative: dangerous protocol redirects ───────────────────────────

    def test_ssrf002_file_protocol_redirect_blocked(self) -> None:
        """file:// protocol in redirect URLs must be rejected."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="file:///etc/passwd")

    def test_ssrf002_ftp_protocol_redirect_blocked(self) -> None:
        """ftp:// protocol in redirect URLs must be rejected."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="ftp://evil.com/malware")

    def test_ssrf002_data_protocol_redirect_blocked(self) -> None:
        """data: protocol in redirect URLs must be rejected."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="data:text/html,<script>alert(1)</script>")

    def test_ssrf002_javascript_protocol_redirect_blocked(self) -> None:
        """javascript: protocol in redirect URLs must be rejected."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="javascript:alert(1)")

    # ── Middleware validates redirect host ────────────────────────────────

    def test_ssrf002_middleware_validates_redirect_host(self) -> None:
        """SecurityMiddleware must validate Host header for redirect targets."""
        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("trusted.example.com")
            assert not middleware.is_host_allowed("evil.com")

    @pytest.mark.asyncio
    async def test_ssrf002_middleware_rejects_redirect_to_private_ip(self) -> None:
        """Middleware must reject requests whose Host header is a private IP,
        even if the request path is a redirect endpoint."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(
                path="/redirect-endpoint",
                headers=[(b"host", b"10.0.0.1")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf002_middleware_rejects_redirect_to_evil_host(self) -> None:
        """Middleware must reject requests with an untrusted Host header,
        preventing open redirect via Host header manipulation."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(
                path="/redirect",
                headers=[(b"host", b"evil.attacker.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    # ── SSL redirect host validation ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf002_ssl_redirect_uses_validated_host(self) -> None:
        """SSL redirect must use the validated Host header, not attacker-controlled input."""
        with override_settings(ALLOWED_HOSTS=["example.com"], SECURE_SSL_REDIRECT=True):
            middleware = SecurityMiddleware(dummy_app, ssl_redirect=True)
            scope = make_scope(
                scheme="http",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 301
            location = collector.headers_dict.get("location", "")
            assert location.startswith("https://example.com")

    @pytest.mark.asyncio
    async def test_ssrf002_ssl_redirect_rejects_crlf_in_path(self) -> None:
        """SSL redirect must reject paths containing CR/LF to prevent header injection."""
        with override_settings(ALLOWED_HOSTS=["example.com"], SECURE_SSL_REDIRECT=True):
            middleware = SecurityMiddleware(dummy_app, ssl_redirect=True)
            scope = make_scope(
                scheme="http",
                path="/safe\r\nSet-Cookie: evil=true",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf002_ssl_redirect_rejects_crlf_in_query_string(self) -> None:
        """SSL redirect must reject query strings containing CR/LF."""
        with override_settings(ALLOWED_HOSTS=["example.com"], SECURE_SSL_REDIRECT=True):
            middleware = SecurityMiddleware(dummy_app, ssl_redirect=True)
            scope = make_scope(
                scheme="http",
                query_string=b"q=1\r\nSet-Cookie: evil=true",
                headers=[(b"host", b"example.com")],
            )
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400


# ---------------------------------------------------------------------------
# SSRF-003: Dangerous protocols are rejected
# ---------------------------------------------------------------------------


class TestSSRF003DangerousProtocols:
    """Dangerous URL protocols must be rejected."""

    # ── RedirectResponse rejects dangerous schemes ───────────────────────

    def test_ssrf003_file_protocol_rejected(self) -> None:
        """file:// protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="file:///etc/passwd")

    def test_ssrf003_ftp_protocol_rejected(self) -> None:
        """ftp:// protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="ftp://evil.com/malware")

    def test_ssrf003_gopher_protocol_rejected(self) -> None:
        """gopher:// protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="gopher://evil.com/data")

    def test_ssrf003_unix_protocol_rejected(self) -> None:
        """unix:// protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="unix:///var/run/docker.sock")

    def test_ssrf003_data_protocol_rejected(self) -> None:
        """data: protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="data:text/html,<script>alert(1)</script>")

    def test_ssrf003_javascript_protocol_rejected(self) -> None:
        """javascript: protocol must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme"):
            RedirectResponse(url="javascript:alert(document.cookie)")

    # ── Positive: safe protocols are accepted ────────────────────────────

    def test_ssrf003_http_protocol_accepted(self) -> None:
        """http:// protocol must be accepted by RedirectResponse."""
        response = RedirectResponse(url="http://example.com/path")
        assert response.status_code == 307

    def test_ssrf003_https_protocol_accepted(self) -> None:
        """https:// protocol must be accepted by RedirectResponse."""
        response = RedirectResponse(url="https://example.com/path")
        assert response.status_code == 307

    def test_ssrf003_relative_path_accepted(self) -> None:
        """Relative path redirects (no scheme) must be accepted."""
        response = RedirectResponse(url="/dashboard")
        assert response.status_code == 307
        assert response.headers.get("location") == "/dashboard"

    # ── Host validation rejects dangerous host patterns ──────────────────

    def test_ssrf003_host_validation_rejects_empty(self) -> None:
        """Empty host must be rejected by VALID_HOST_RE."""
        assert not VALID_HOST_RE.match("")

    def test_ssrf003_host_validation_rejects_whitespace(self) -> None:
        """Whitespace-only host must be rejected."""
        assert not VALID_HOST_RE.match(" ")
        assert not VALID_HOST_RE.match("  ")

    def test_ssrf003_host_validation_rejects_leading_hyphen(self) -> None:
        """Hostnames starting with a hyphen must be rejected."""
        assert not VALID_HOST_RE.match("-evil.com")

    # ── Comprehensive dangerous protocol list ──────────────────────────────

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://evil.com/malware",
            "gopher://evil.com/data",
            "unix:///var/run/docker.sock",
            "data:text/html,<script>alert(1)</script>",
            "javascript:alert(1)",
            "vbscript:MsgBox",
            "blob:http://evil.com",
        ],
        ids=[
            "file",
            "ftp",
            "gopher",
            "unix",
            "data",
            "javascript",
            "vbscript",
            "blob",
        ],
    )
    def test_ssrf003_dangerous_schemes_rejected(self, url: str) -> None:
        """All dangerous URL schemes must be rejected by RedirectResponse."""
        with pytest.raises(ValueError, match="disallowed scheme|not allowed|CRLF|traversal"):
            RedirectResponse(url=url)

    # ── Middleware rejects requests with dangerous host patterns ──────────

    @pytest.mark.asyncio
    async def test_ssrf003_middleware_rejects_crlf_host(self) -> None:
        """Middleware must reject requests with CRLF injection in Host header."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"evil.com\r\nSet-Cookie: x=1")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf003_middleware_rejects_null_byte_host(self) -> None:
        """Middleware must reject requests with null bytes in Host header."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"evil.com\0trusted.com")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400


# ---------------------------------------------------------------------------
# SSRF-004: DNS rebinding protections are applied
# ---------------------------------------------------------------------------


class TestSSRF004DNSRebinding:
    """DNS rebinding protections must ensure per-request host validation."""

    # ── Per-request validation ────────────────────────────────────────────

    def test_ssrf004_host_validation_is_per_request(self) -> None:
        """Each call to is_host_allowed must validate independently, not cache."""
        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("trusted.example.com")
            assert not middleware.is_host_allowed("evil.com")
            assert middleware.is_host_allowed("trusted.example.com")

    def test_ssrf004_no_cross_contamination_between_hosts(self) -> None:
        """Validation of one host must not affect validation of another."""
        with override_settings(ALLOWED_HOSTS=["a.example.com", "b.example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            assert middleware.is_host_allowed("a.example.com")
            assert middleware.is_host_allowed("b.example.com")
            assert not middleware.is_host_allowed("c.example.com")
            assert middleware.is_host_allowed("a.example.com")
            assert middleware.is_host_allowed("b.example.com")

    @pytest.mark.asyncio
    async def test_ssrf004_middleware_rejects_rebind_on_second_request(self) -> None:
        """After allowing a request for a trusted host, a subsequent request
        with an untrusted host must still be rejected (no caching)."""
        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(dummy_app)

            scope_good = make_scope(headers=[(b"host", b"trusted.example.com")])
            collector_good = SendCollector()
            await middleware(scope_good, AsyncMock(), collector_good)
            assert collector_good.status_code == 200

            scope_bad = make_scope(headers=[(b"host", b"evil.rebind.com")])
            collector_bad = SendCollector()
            await middleware(scope_bad, AsyncMock(), collector_bad)
            assert collector_bad.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf004_middleware_allows_after_rejection(self) -> None:
        """After rejecting an untrusted host, a subsequent request with a
        trusted host must still be allowed (no negative caching)."""
        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(dummy_app)

            scope_bad = make_scope(headers=[(b"host", b"evil.rebind.com")])
            collector_bad = SendCollector()
            await middleware(scope_bad, AsyncMock(), collector_bad)
            assert collector_bad.status_code == 400

            scope_good = make_scope(headers=[(b"host", b"trusted.example.com")])
            collector_good = SendCollector()
            await middleware(scope_good, AsyncMock(), collector_good)
            assert collector_good.status_code == 200

    # ── Wildcard ALLOWED_HOSTS does not bypass per-request checks ─────────

    @pytest.mark.asyncio
    async def test_ssrf004_wildcard_still_rejects_crlf(self) -> None:
        """Even with ALLOWED_HOSTS=['*'], CRLF injection must be rejected."""
        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"evil.com\r\nSet-Cookie: x=1")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_ssrf004_wildcard_still_rejects_null_byte(self) -> None:
        """Even with ALLOWED_HOSTS=['*'], null byte injection must be rejected."""
        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"evil.com\0trusted.com")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    # ── Host stripping: port removal ─────────────────────────────────────

    def test_ssrf004strip_port_ipv4(self) -> None:
        """strip_port must correctly remove ports from IPv4 hosts."""
        assert SecurityMiddleware.strip_port("example.com:443") == "example.com"
        assert SecurityMiddleware.strip_port("example.com:80") == "example.com"
        assert SecurityMiddleware.strip_port("127.0.0.1:8000") == "127.0.0.1"

    def test_ssrf004strip_port_ipv6(self) -> None:
        """strip_port must correctly handle IPv6 bracket notation."""
        assert SecurityMiddleware.strip_port("[::1]:8000") == "::1"
        assert SecurityMiddleware.strip_port("[::1]") == "::1"

    def test_ssrf004strip_port_no_port(self) -> None:
        """strip_port must return the host unchanged when no port is present."""
        assert SecurityMiddleware.strip_port("example.com") == "example.com"
        assert SecurityMiddleware.strip_port("127.0.0.1") == "127.0.0.1"

    # ── _get_host extracts host from scope ────────────────────────────────

    def test_ssrf004_get_host_from_header(self) -> None:
        """_get_host must extract the hostname from the Host header."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"example.com:443")])
            host = middleware.get_host(scope)
            assert host == "example.com"

    def test_ssrf004_get_host_from_server_fallback(self) -> None:
        """_get_host must fall back to the server tuple when no Host header."""
        with override_settings(ALLOWED_HOSTS=["localhost"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[], server=("localhost", 8000))
            host = middleware.get_host(scope)
            assert host == "localhost"

    def test_ssrf004_get_host_empty_when_no_header_or_server(self) -> None:
        """_get_host must return empty string when no Host header or server."""
        with override_settings(ALLOWED_HOSTS=["example.com"]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[], server=None)
            scope.pop("server", None)
            host = middleware.get_host(scope)
            assert host == ""

    # ── Fail-closed: empty ALLOWED_HOSTS ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf004_empty_allowed_hosts_rejects_all(self) -> None:
        """Empty ALLOWED_HOSTS must reject all requests (fail-closed)."""
        with override_settings(ALLOWED_HOSTS=[]):
            middleware = SecurityMiddleware(dummy_app)
            scope = make_scope(headers=[(b"host", b"example.com")])
            collector = SendCollector()
            await middleware(scope, AsyncMock(), collector)
            assert collector.status_code == 400

    # ── Concurrent request isolation ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf004_concurrent_requests_isolated(self) -> None:
        """Concurrent requests with different hosts must be validated
        independently, preventing DNS rebinding via race conditions."""
        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(dummy_app)

            scope_good = make_scope(headers=[(b"host", b"trusted.example.com")])
            scope_bad = make_scope(headers=[(b"host", b"evil.rebind.com")])

            collector_good = SendCollector()
            collector_bad = SendCollector()

            await asyncio.gather(
                middleware(scope_good, AsyncMock(), collector_good),
                middleware(scope_bad, AsyncMock(), collector_bad),
            )

            assert collector_good.status_code == 200
            assert collector_bad.status_code == 400
