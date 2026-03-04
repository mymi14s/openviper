import pytest

from openviper.middleware.security import SecurityMiddleware


@pytest.mark.asyncio
async def test_security_middleware_fixed_headers():
    async def dummy_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    mw = SecurityMiddleware(
        dummy_app,
        hsts_seconds=31536000,
        hsts_include_subdomains=True,
        hsts_preload=True,
        x_frame_options="SAMEORIGIN",
        content_type_nosniff=True,
        xss_filter=True,
        csp={"default-src": ["'self'"], "img-src": ["*", "data:"]},
    )

    mw._is_host_allowed = lambda host: True  # mock host check
    scope = {"type": "http", "headers": [(b"host", b"localhost")]}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await mw(scope, None, fake_send)
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in sends[0]["headers"]}

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains; preload"
    assert headers["x-xss-protection"] == "1; mode=block"
    assert headers["content-security-policy"] == "default-src 'self'; img-src * data:"


@pytest.mark.asyncio
async def test_security_middleware_csp_string():
    mw = SecurityMiddleware(None, csp="default-src 'none'")
    assert (b"content-security-policy", b"default-src 'none'") in mw._fixed_headers


def test_security_middleware_get_host():
    mw = SecurityMiddleware(None)

    assert mw._get_host({"headers": [(b"host", b"example.com")]}) == "example.com"
    assert mw._get_host({"headers": [(b"host", b"example.com:8080")]}) == "example.com"
    assert mw._get_host({"server": ("fallback.com", 80)}) == "fallback.com"
    assert mw._get_host({}) == ""


def test_security_middleware_allowed_hosts():
    from unittest.mock import patch

    class MockSettings:
        ALLOWED_HOSTS = ["example.com", ".dev.local", "*"]

    with patch("openviper.middleware.security.settings", MockSettings):
        mw = SecurityMiddleware(None)
        assert mw._is_host_allowed("example.com") is True
        assert mw._is_host_allowed("api.dev.local") is True
        assert mw._is_host_allowed("dev.local") is True
        # Since "*" is in ALLOWED_HOSTS, everything is allowed
        assert mw._is_host_allowed("hacker.com") is True

    class MockStrictSettings:
        ALLOWED_HOSTS = ["example.com"]

    with patch("openviper.middleware.security.settings", MockStrictSettings):
        mw2 = SecurityMiddleware(None)
        assert mw2._is_host_allowed("example.com") is True
        assert mw2._is_host_allowed("hacker.com") is False


@pytest.mark.asyncio
async def test_security_middleware_ssl_redirect():
    mw = SecurityMiddleware(None, ssl_redirect=True)
    mw._is_host_allowed = lambda host: True

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/login",
        "query_string": b"next=/home",
        "headers": [(b"host", b"localhost:8000")],
    }

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await mw(scope, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["status"] == 301
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in sends[0]["headers"]}
    assert headers["location"] == "https://localhost:8000/login?next=/home"


@pytest.mark.asyncio
async def test_security_middleware_disallowed_host():
    mw = SecurityMiddleware(None)
    mw._is_host_allowed = lambda host: False

    scope = {"type": "http", "headers": [(b"host", b"evil.com")]}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await mw(scope, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["status"] == 400
    assert b"Invalid HTTP_HOST header: 'evil.com'" in sends[1]["body"]


@pytest.mark.asyncio
async def test_security_middleware_non_http():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("passed")

    mw = SecurityMiddleware(dummy_app)
    await mw({"type": "websocket"}, None, None)
    assert calls == ["passed"]
