"""Integration tests for RateLimitMiddleware and rate_limit decorator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from openviper.app import OpenViper
from openviper.http.request import Request
from openviper.middleware.ratelimit import (
    RateLimitMiddleware,
    _SlidingWindowCounter,
    rate_limit,
)

# ---------------------------------------------------------------------------
# _SlidingWindowCounter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counter_allows_within_limit():
    counter = _SlidingWindowCounter(max_requests=5, window_seconds=60)
    allowed, remaining = await counter.is_allowed("testkey")
    assert allowed is True
    assert remaining == 4


@pytest.mark.asyncio
async def test_counter_denies_over_limit():
    counter = _SlidingWindowCounter(max_requests=2, window_seconds=60)
    await counter.is_allowed("key")
    await counter.is_allowed("key")
    allowed, remaining = await counter.is_allowed("key")
    assert allowed is False
    assert remaining == 0


@pytest.mark.asyncio
async def test_counter_independent_keys():
    counter = _SlidingWindowCounter(max_requests=1, window_seconds=60)
    ok_a, _ = await counter.is_allowed("user_a")
    ok_b, _ = await counter.is_allowed("user_b")
    assert ok_a is True
    assert ok_b is True


@pytest.mark.asyncio
async def test_counter_eviction_runs_after_interval():
    """Force TTL eviction path by manipulating _last_evict."""
    import time

    counter = _SlidingWindowCounter(max_requests=10, window_seconds=1)
    await counter.is_allowed("somekey")
    # Push last_evict into the past to trigger the eviction branch
    counter._last_evict = time.monotonic() - 400.0
    # Should still work without error
    allowed, _ = await counter.is_allowed("somekey")
    assert allowed is True


# ---------------------------------------------------------------------------
# RateLimitMiddleware — middleware-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ratelimit_middleware_allows_under_limit():
    app = OpenViper()

    @app.get("/ping")
    async def ping(request: Request):
        from openviper.http.response import JSONResponse

        return JSONResponse({"ok": True})

    wrapped = RateLimitMiddleware(app, max_requests=10, window_seconds=60)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ping")
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "10" in resp.headers["x-ratelimit-limit"]


@pytest.mark.asyncio
async def test_ratelimit_middleware_returns_429_over_limit():
    app = OpenViper()

    @app.get("/limited")
    async def limited(request: Request):
        from openviper.http.response import JSONResponse

        return JSONResponse({"ok": True})

    wrapped = RateLimitMiddleware(app, max_requests=2, window_seconds=60)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="http://testserver"
    ) as client:
        await client.get("/limited")
        await client.get("/limited")
        resp = await client.get("/limited")

    assert resp.status_code == 429
    data = resp.json()
    assert data["detail"] == "Too many requests"
    assert "retry_after" in data


@pytest.mark.asyncio
async def test_ratelimit_middleware_non_http_scope_passthrough():
    """Websocket-scope requests bypass the rate-limit check."""
    inner_called = []

    async def inner_app(scope, receive, send):
        inner_called.append(scope["type"])

    wrapped = RateLimitMiddleware(inner_app, max_requests=1, window_seconds=60)
    await wrapped({"type": "lifespan"}, None, None)
    assert "lifespan" in inner_called


@pytest.mark.asyncio
async def test_ratelimit_middleware_x_forwarded_for_header():
    """IP is read from X-Forwarded-For header when client tuple is absent."""
    app = OpenViper()

    @app.get("/ip")
    async def ip_view(request: Request):
        from openviper.http.response import JSONResponse

        return JSONResponse({"ok": True})

    wrapped = RateLimitMiddleware(app, max_requests=5, window_seconds=60)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ip", headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ratelimit_middleware_reads_settings_defaults():
    """When no args passed, middleware reads RATE_LIMIT_REQUESTS/WINDOW from settings."""
    with patch("openviper.middleware.ratelimit.settings") as ms:
        ms.RATE_LIMIT_REQUESTS = 50
        ms.RATE_LIMIT_WINDOW = 30
        mw = RateLimitMiddleware(app=AsyncMock())
    assert mw.max_requests == 50
    assert mw.window_seconds == 30.0


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_decorator_allows_under_limit():
    @rate_limit(max_requests=5, window_seconds=60)
    async def my_view(request: Request):
        return "ok"

    mock_req = MagicMock(spec=Request)
    mock_req.client = ("127.0.0.1", 1234)

    result = await my_view(mock_req)
    assert result == "ok"


@pytest.mark.asyncio
async def test_rate_limit_decorator_raises_over_limit():
    from openviper.exceptions import TooManyRequests

    # Fresh decorated function with a new counter (limit=1)
    @rate_limit(max_requests=1, window_seconds=60)
    async def expensive(request: Request):
        return "ok"

    # Use unique IP that no other test has used
    mock_req = MagicMock(spec=Request)
    mock_req.client = ("192.0.2.99", 9000)

    await expensive(mock_req)  # consumes the 1 allowed request
    with pytest.raises(TooManyRequests):
        await expensive(mock_req)  # now over limit


@pytest.mark.asyncio
async def test_rate_limit_decorator_no_request_arg_skips_check():
    """If no Request is found in args/kwargs the decorator skips rate-limit."""

    @rate_limit(max_requests=1, window_seconds=60)
    async def no_req_view():
        return "fine"

    # Call twice — should never raise since there's no Request to key on
    assert await no_req_view() == "fine"
    assert await no_req_view() == "fine"


@pytest.mark.asyncio
async def test_rate_limit_decorator_reads_request_from_kwargs():
    @rate_limit(max_requests=5, window_seconds=60)
    async def kw_view(**kwargs):
        return "kwok"

    mock_req = MagicMock(spec=Request)
    mock_req.client = ("192.168.1.1", 80)

    result = await kw_view(request=mock_req)
    assert result == "kwok"


# ---------------------------------------------------------------------------
# Custom key_func
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ratelimit_middleware_custom_key_func():
    """Custom key_func overrides the default IP-based keying."""
    app = OpenViper()

    @app.get("/custom")
    async def custom_view(request: Request):
        from openviper.http.response import JSONResponse

        return JSONResponse({"ok": True})

    # Key all requests as "global" → they share the same bucket
    wrapped = RateLimitMiddleware(
        app, max_requests=1, window_seconds=60, key_func=lambda _scope: "global"
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="http://testserver"
    ) as client:
        r1 = await client.get("/custom")
        r2 = await client.get("/custom")

    assert r1.status_code == 200
    assert r2.status_code == 429
