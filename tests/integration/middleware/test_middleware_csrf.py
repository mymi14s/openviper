import pytest

from openviper.middleware.csrf import CSRFMiddleware


@pytest.mark.asyncio
async def test_csrf_middleware_safe_method():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = CSRFMiddleware(app)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    messages = []

    async def send(message):
        messages.append(message)

    await middleware(scope, None, send)
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_csrf_middleware_unsafe_method_fail():
    async def app(scope, receive, send):
        pass

    middleware = CSRFMiddleware(app)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": []}  # No CSRF token

    messages = []

    async def send(message):
        messages.append(message)

    await middleware(scope, None, send)
    # Should be 403 Forbidden
    start_message = next(m for m in messages if m["type"] == "http.response.start")
    assert start_message["status"] == 403
