import pytest

from openviper.contrib.default.middleware import DefaultLandingMiddleware


@pytest.mark.asyncio
async def test_landing_middleware_bypass():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("bypassed")

    # Bypass because has custom root
    mw = DefaultLandingMiddleware(dummy_app, has_custom_root=True)
    await mw({"type": "http", "method": "GET", "path": "/"}, None, None)
    assert calls == ["bypassed"]

    # Bypass non-http
    calls.clear()
    mw2 = DefaultLandingMiddleware(dummy_app, has_custom_root=False)
    await mw2({"type": "websocket", "method": "GET", "path": "/"}, None, None)
    assert calls == ["bypassed"]

    # Bypass non-root path
    calls.clear()
    await mw2({"type": "http", "method": "GET", "path": "/api"}, None, None)
    assert calls == ["bypassed"]


@pytest.mark.asyncio
async def test_landing_middleware_debug():
    async def dummy_app(scope, receive, send):
        pass

    mw = DefaultLandingMiddleware(dummy_app, debug=True, version="1.0.0", has_custom_root=False)

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await mw({"type": "http", "method": "GET", "path": "/"}, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["status"] == 200
    assert b"1.0.0" in sends[1]["body"]
    assert b"OpenViper" in sends[1]["body"]


@pytest.mark.asyncio
async def test_landing_middleware_production():
    async def dummy_app(scope, receive, send):
        pass

    mw = DefaultLandingMiddleware(dummy_app, debug=False, has_custom_root=False)

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await mw({"type": "http", "method": "GET", "path": "/"}, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["status"] == 404
    assert b"<h1>404 Not Found</h1>" in sends[1]["body"]
