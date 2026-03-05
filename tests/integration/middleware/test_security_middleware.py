"""Integration tests for SecurityMiddleware header injection, HSTS, SSL redirect."""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from openviper.conf.settings import settings
from openviper.middleware.security import SecurityMiddleware


def _patch_hosts(hosts):
    """Patch ``settings.ALLOWED_HOSTS`` to *hosts* for the duration of a ``with`` block.

    The frozen Settings dataclass cannot be mutated directly, so we swap
    ``settings._instance`` for a replaced copy for the duration of the block.
    """
    if not settings._configured:
        settings._setup()
    new_instance = dataclasses.replace(settings._instance, ALLOWED_HOSTS=tuple(hosts))
    return patch.object(settings, "_instance", new_instance)


async def _make_basic_app():
    """A minimal ASGI app that returns 200 OK."""

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"OK"})

    return app


def _build_scope(path="/", method="GET", scheme="http", headers=None, host="localhost"):
    h = [(b"host", host.encode())]
    if headers:
        h.extend(headers)
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": h,
        "scheme": scheme,
        "server": ("localhost", 80),
    }


async def _collect_messages(middleware, scope):
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)
    return messages


# ---------------------------------------------------------------------------
# Default headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_default_headers():
    """SecurityMiddleware adds X-Content-Type-Options and X-Frame-Options by default."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    header_names = [k.lower() for k, _ in start["headers"]]
    assert b"x-content-type-options" in header_names
    assert b"x-frame-options" in header_names
    assert b"referrer-policy" in header_names


@pytest.mark.asyncio
async def test_security_nosniff_header_value():
    """X-Content-Type-Options is 'nosniff'."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, content_type_nosniff=True)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers.get(b"x-content-type-options") == b"nosniff"


@pytest.mark.asyncio
async def test_security_x_frame_options_deny():
    """X-Frame-Options defaults to DENY."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, x_frame_options="DENY")

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers.get(b"x-frame-options") == b"DENY"


@pytest.mark.asyncio
async def test_security_x_frame_options_sameorigin():
    """X-Frame-Options can be set to SAMEORIGIN."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, x_frame_options="SAMEORIGIN")

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers.get(b"x-frame-options") == b"SAMEORIGIN"


# ---------------------------------------------------------------------------
# HSTS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_hsts_header_added():
    """HSTS header is present when hsts_seconds > 0."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, hsts_seconds=31536000)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert b"strict-transport-security" in headers
    assert b"max-age=31536000" in headers[b"strict-transport-security"]


@pytest.mark.asyncio
async def test_security_hsts_with_subdomains_and_preload():
    """HSTS includes includeSubDomains and preload when configured."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(
            app,
            hsts_seconds=31536000,
            hsts_include_subdomains=True,
            hsts_preload=True,
        )

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    hsts_val = headers[b"strict-transport-security"].decode()
    assert "includeSubDomains" in hsts_val
    assert "preload" in hsts_val


@pytest.mark.asyncio
async def test_security_hsts_not_added_when_zero():
    """No HSTS header when hsts_seconds=0."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, hsts_seconds=0)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    header_names = [k for k, _ in start["headers"]]
    assert b"strict-transport-security" not in header_names


# ---------------------------------------------------------------------------
# SSL redirect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_ssl_redirect():
    """ssl_redirect=True redirects HTTP requests to HTTPS."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, ssl_redirect=True)

    scope = _build_scope(path="/some/path", scheme="http", host="example.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 301
    headers = dict(start["headers"])
    assert b"https://example.com/some/path" in headers[b"location"]


@pytest.mark.asyncio
async def test_security_no_ssl_redirect_on_https():
    """No redirect when request is already HTTPS."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, ssl_redirect=True)

    scope = _build_scope(scheme="https")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200


# ---------------------------------------------------------------------------
# Allowed hosts check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_disallowed_host_returns_400():
    """Requests with disallowed hosts return 400."""
    with _patch_hosts(["example.com"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope(host="attacker.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 400


@pytest.mark.asyncio
async def test_security_wildcard_allows_any_host():
    """ALLOWED_HOSTS=['*'] allows all hosts."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope(host="anything.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_security_subdomain_wildcard_allowed():
    """ALLOWED_HOSTS=['.example.com'] allows subdomains."""
    with _patch_hosts([".example.com"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope(host="sub.example.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_security_subdomain_wildcard_base_domain_allowed():
    """.example.com pattern also allows example.com (base domain)."""
    with _patch_hosts([".example.com"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope(host="example.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_security_empty_allowed_hosts_rejects_all():
    """Empty ALLOWED_HOSTS rejects all requests."""
    with _patch_hosts([]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app)

    scope = _build_scope(host="example.com")
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 400


# ---------------------------------------------------------------------------
# CSP header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_csp_dict():
    """CSP dict is serialized to header string."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        csp = {"default-src": "'self'", "img-src": ["*", "data:"]}
        middleware = SecurityMiddleware(app, csp=csp)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert b"content-security-policy" in headers


@pytest.mark.asyncio
async def test_security_csp_string():
    """CSP string is used directly as header value."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        csp_str = "default-src 'self'; img-src *"
        middleware = SecurityMiddleware(app, csp=csp_str)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers[b"content-security-policy"] == csp_str.encode()


# ---------------------------------------------------------------------------
# Non-HTTP scope pass-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_websocket_passes_through():
    """Non-HTTP scopes pass through without modification."""
    with _patch_hosts(["*"]):
        called = []

        async def app(scope, receive, send):
            called.append(scope["type"])

        middleware = SecurityMiddleware(app)

    ws_scope = {"type": "websocket", "path": "/ws"}
    await middleware(ws_scope, None, None)
    assert called == ["websocket"]


# ---------------------------------------------------------------------------
# XSS filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_xss_filter_header():
    """XSS filter adds X-XSS-Protection header."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        # xss_filter=True is explicit — no settings read needed for the filter flag
        middleware = SecurityMiddleware(app, xss_filter=True)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers.get(b"x-xss-protection") == b"1; mode=block"


@pytest.mark.asyncio
async def test_security_no_xss_filter():
    """No XSS header when xss_filter=False."""
    with _patch_hosts(["*"]):
        app = await _make_basic_app()
        middleware = SecurityMiddleware(app, xss_filter=False)

    scope = _build_scope()
    messages = await _collect_messages(middleware, scope)

    start = next(m for m in messages if m["type"] == "http.response.start")
    header_names = [k for k, _ in start["headers"]]
    assert b"x-xss-protection" not in header_names
