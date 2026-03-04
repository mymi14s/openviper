import time
from unittest.mock import MagicMock, patch

import pytest

from openviper.exceptions import TooManyRequests
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.middleware.ratelimit import RateLimitMiddleware, _SlidingWindowCounter, rate_limit


@pytest.mark.asyncio
async def test_sliding_window_counter():
    counter = _SlidingWindowCounter(max_requests=2, window_seconds=0.1)

    # 1. First request
    allowed, rem = await counter.is_allowed("test-ip")
    assert allowed is True
    assert rem == 1

    # 2. Second request
    allowed, rem = await counter.is_allowed("test-ip")
    assert allowed is True
    assert rem == 0

    # 3. Third request -> Rejected
    allowed, rem = await counter.is_allowed("test-ip")
    assert allowed is False
    assert rem == 0

    # Wait for window to expire
    time.sleep(0.15)

    # 4. Request after expiration -> Allowed
    allowed, rem = await counter.is_allowed("test-ip")
    assert allowed is True
    assert rem == 1


def test_ratelimit_default_key():
    mw = RateLimitMiddleware(None)

    # Test client tuple
    assert mw._default_key({"client": ("127.0.0.1", 8080)}) == "127.0.0.1"

    # Test forwarded for
    assert (
        mw._default_key({"headers": [(b"x-forwarded-for", b"10.0.0.1, 192.168.0.1")]}) == "10.0.0.1"
    )

    # Unknown
    assert mw._default_key({}) == "unknown"


@pytest.mark.asyncio
async def test_ratelimit_middleware():
    async def dummy_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = RateLimitMiddleware(dummy_app, max_requests=1, window_seconds=60)
    scope = {"type": "http", "client": ("127.0.0.1", 1234)}

    sends_first = []

    async def track_first(msg):
        sends_first.append(msg)

    await mw(scope, None, track_first)

    # Headers should be injected
    assert len(sends_first) == 2
    assert sends_first[0]["status"] == 200
    headers = dict(sends_first[0]["headers"])
    assert headers[b"x-ratelimit-limit"] == b"1"
    assert headers[b"x-ratelimit-remaining"] == b"0"

    # Second request exceeds limit
    sends_second = []

    async def track_second(msg):
        sends_second.append(msg)

    await mw(scope, None, track_second)

    assert len(sends_second) == 2
    assert sends_second[0]["status"] == 429
    headers_second = dict(sends_second[0]["headers"])
    assert headers_second[b"retry-after"] == b"60"


@pytest.mark.asyncio
async def test_ratelimit_middleware_non_http():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("passed")

    mw = RateLimitMiddleware(dummy_app)
    await mw({"type": "websocket"}, None, None)
    assert calls == ["passed"]


@pytest.mark.asyncio
async def test_ratelimit_decorator():
    # Setup test function
    @rate_limit(max_requests=1, window_seconds=60)
    async def my_view(request):
        return "ok"

    scope = {"type": "http", "client": ("10.0.0.2", 8080)}
    req = Request(scope)

    res1 = await my_view(req)
    assert res1 == "ok"

    with pytest.raises(TooManyRequests):
        await my_view(req)

    # Test kwargs
    res3 = await my_view(request=Request({"type": "http", "client": ("10.0.0.3", 8080)}))
    assert res3 == "ok"


@pytest.mark.asyncio
async def test_sliding_window_counter_stripe_isolation():
    """Exhausting one key's quota must not affect a different key.

    This validates that the 256-stripe lock design keeps per-key counters
    independent: key-a being rate-limited does not block key-b.
    """
    counter = _SlidingWindowCounter(max_requests=1, window_seconds=60)

    # Exhaust key-a (1 allowed + 1 rejected to confirm exhaustion).
    allowed_a1, _ = await counter.is_allowed("192.0.2.1")
    assert allowed_a1 is True
    allowed_a2, _ = await counter.is_allowed("192.0.2.1")
    assert allowed_a2 is False

    # key-b should be completely independent — its window is fresh.
    allowed_b, _ = await counter.is_allowed("192.0.2.2")
    assert allowed_b is True
