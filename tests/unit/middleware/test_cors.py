import pytest

from openviper.middleware.cors import CORSMiddleware


async def dummy_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_cors_origin_allowed():
    cors = CORSMiddleware(dummy_app, allowed_origins=["https://example.com", "*.dev.local"])

    assert cors._origin_allowed("https://example.com") is True
    assert cors._origin_allowed("http://api.dev.local") is True
    assert cors._origin_allowed("https://other.com") is False

    cors_all = CORSMiddleware(dummy_app, allowed_origins=["*"])
    assert cors_all._origin_allowed("https://anything.com") is True


@pytest.mark.asyncio
async def test_cors_non_http():
    cors = CORSMiddleware(dummy_app)
    scope = {"type": "websocket"}

    calls = []

    async def fake_app(scope, receive, send):
        calls.append("app_bypassed")

    cors.app = fake_app
    await cors(scope, None, None)
    assert calls == ["app_bypassed"]


@pytest.mark.asyncio
async def test_cors_no_origin():
    # If no Origin header, pass through unchanged
    cors = CORSMiddleware(dummy_app)
    scope = {"type": "http", "headers": []}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await cors(scope, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["headers"] == []


@pytest.mark.asyncio
async def test_cors_preflight():
    cors = CORSMiddleware(
        dummy_app,
        allowed_origins=["*"],
        allowed_methods=["GET", "POST"],
        allowed_headers=["x-custom"],
        expose_headers=["x-exposed"],
        max_age=300,
    )
    scope = {"type": "http", "method": "OPTIONS", "headers": [(b"origin", b"https://test.com")]}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    # Preflight should not call the app, but return 204 directly
    await cors(scope, None, fake_send)
    assert len(sends) == 2

    start_msg = sends[0]
    assert start_msg["status"] == 204
    headers_dict = {k.decode("latin-1"): v.decode("latin-1") for k, v in start_msg["headers"]}

    assert headers_dict["access-control-allow-origin"] == "https://test.com"
    assert headers_dict["access-control-allow-credentials"] == "true"
    assert headers_dict["access-control-allow-methods"] == "GET, POST"
    assert headers_dict["access-control-allow-headers"] == "x-custom"
    assert headers_dict["access-control-max-age"] == "300"
    assert headers_dict["access-control-expose-headers"] == "x-exposed"


@pytest.mark.asyncio
async def test_cors_simple_request():
    cors = CORSMiddleware(dummy_app, allowed_origins=["https://abc.com"])
    scope = {"type": "http", "method": "GET", "headers": [(b"origin", b"https://abc.com")]}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await cors(scope, None, fake_send)
    assert len(sends) == 2

    start_msg = sends[0]
    assert start_msg["status"] == 200
    headers_dict = {k.decode("latin-1"): v.decode("latin-1") for k, v in start_msg["headers"]}

    # App headers + CORS payload
    assert headers_dict["access-control-allow-origin"] == "https://abc.com"
    assert headers_dict["access-control-allow-credentials"] == "true"
    # method/headers/max-age are strictly for preflight
    assert "access-control-allow-methods" not in headers_dict


@pytest.mark.asyncio
async def test_cors_disallowed_origin():
    cors = CORSMiddleware(dummy_app, allowed_origins=["https://abc.com"])
    scope = {"type": "http", "method": "GET", "headers": [(b"origin", b"https://BAD.com")]}

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await cors(scope, None, fake_send)

    start_msg = sends[0]
    headers_dict = {k.decode("latin-1"): v.decode("latin-1") for k, v in start_msg["headers"]}

    # Shouldn"t inject allow-origin if disallowed
    assert "access-control-allow-origin" not in headers_dict
