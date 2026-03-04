import pytest

from openviper.http.response import Response
from openviper.middleware.cors import CORSMiddleware


@pytest.mark.asyncio
async def test_cors_middleware_basic():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = CORSMiddleware(app, allowed_origins=["http://example.com"])

    scope = {"type": "http", "method": "GET", "headers": [(b"origin", b"http://example.com")]}

    messages = []

    async def send(message):
        messages.append(message)

    await middleware(scope, None, send)

    # Check headers
    start_message = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start_message["headers"])
    assert headers[b"access-control-allow-origin"] == b"http://example.com"


@pytest.mark.asyncio
async def test_cors_middleware_preflight():
    async def app(scope, receive, send):
        pass  # App should not be called for preflight

    middleware = CORSMiddleware(app, allowed_origins=["*"])

    scope = {
        "type": "http",
        "method": "OPTIONS",
        "headers": [(b"origin", b"http://someorigin.com")],
    }

    messages = []

    async def send(message):
        messages.append(message)

    await middleware(scope, None, send)

    start_message = next(m for m in messages if m["type"] == "http.response.start")
    assert start_message["status"] == 204
    headers = dict(start_message["headers"])
    assert headers[b"access-control-allow-origin"] == b"http://someorigin.com"
    assert b"access-control-allow-methods" in headers
