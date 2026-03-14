"""Unit tests for openviper.middleware.ratelimit — SlidingWindowCounter, RateLimitMiddleware, decorator."""

import asyncio

import pytest

from openviper.exceptions import TooManyRequests
from openviper.http.request import Request
from openviper.middleware.ratelimit import RateLimitMiddleware, _SlidingWindowCounter, rate_limit


def _make_scope(client=("127.0.0.1", 8000), headers=None):
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": list(headers or []),
        "client": client,
        "query_string": b"",
    }


def _make_request(ip="127.0.0.1"):
    async def receive():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": (ip, 8000),
    }
    return Request(scope, receive)


async def _run_mw(mw, scope):
    """Run middleware, return list of ASGI messages sent."""
    messages = []

    async def send(msg):
        messages.append(msg)

    await mw(scope, None, send)
    return messages


# ---------------------------------------------------------------------------
# SlidingWindowCounter
# ---------------------------------------------------------------------------


class TestSlidingWindowCounter:
    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        counter = _SlidingWindowCounter(max_requests=5, window_seconds=60.0)
        allowed, remaining = await counter.is_allowed("client1")
        assert allowed is True
        assert remaining == 4

    @pytest.mark.asyncio
    async def test_blocks_after_limit(self):
        counter = _SlidingWindowCounter(max_requests=2, window_seconds=60.0)
        await counter.is_allowed("client1")
        await counter.is_allowed("client1")
        allowed, remaining = await counter.is_allowed("client1")
        assert allowed is False
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_independent_keys(self):
        counter = _SlidingWindowCounter(max_requests=1, window_seconds=60.0)
        allowed1, _ = await counter.is_allowed("client1")
        allowed2, _ = await counter.is_allowed("client2")
        assert allowed1 is True
        assert allowed2 is True

    @pytest.mark.asyncio
    async def test_remaining_decrements(self):
        counter = _SlidingWindowCounter(max_requests=3, window_seconds=60.0)
        _, r1 = await counter.is_allowed("x")
        _, r2 = await counter.is_allowed("x")
        assert r1 == 2
        assert r2 == 1

    @pytest.mark.asyncio
    async def test_window_expiry_resets_count(self):
        """After the window expires the key should be allowed again."""
        counter = _SlidingWindowCounter(max_requests=1, window_seconds=0.05)
        allowed1, _ = await counter.is_allowed("expire-test")
        assert allowed1 is True
        allowed2, _ = await counter.is_allowed("expire-test")
        assert allowed2 is False
        await asyncio.sleep(0.1)
        allowed3, _ = await counter.is_allowed("expire-test")
        assert allowed3 is True

    @pytest.mark.asyncio
    async def test_stripe_isolation(self):
        """Keys in different stripes must not interfere with each other."""
        counter = _SlidingWindowCounter(max_requests=1, window_seconds=60.0)
        for i in range(50):
            allowed, _ = await counter.is_allowed(f"key-{i}")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_concurrent_same_key_safe(self):
        """Concurrent calls for the same key must not exceed max_requests."""
        counter = _SlidingWindowCounter(max_requests=5, window_seconds=60.0)
        results = await asyncio.gather(*[counter.is_allowed("concurrent") for _ in range(10)])
        allowed_count = sum(1 for ok, _ in results if ok)
        assert allowed_count == 5


class TestSlidingWindowEviction:
    @pytest.mark.asyncio
    async def test_stale_entries_evicted_via_short_window(self):
        """Entries whose window expires must not count toward the limit."""
        counter = _SlidingWindowCounter(max_requests=1, window_seconds=0.02, evict_interval=0.0)
        await counter.is_allowed("evict-key")
        await asyncio.sleep(0.05)
        allowed, _ = await counter.is_allowed("evict-key")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_new_bucket_created_on_first_call(self):
        counter = _SlidingWindowCounter(max_requests=5, window_seconds=60.0)
        allowed, remaining = await counter.is_allowed("brand_new_key")
        assert allowed is True
        assert remaining == 4


# ---------------------------------------------------------------------------
# RateLimitMiddleware — happy path
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_allows_request_within_limit(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=10, window_seconds=60)
        msgs = await _run_mw(mw, _make_scope())
        assert msgs[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_blocks_request_over_limit(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        scope = _make_scope(client=("1.2.3.4", 9000))
        await _run_mw(mw, scope)  # 1st — allowed
        msgs = await _run_mw(mw, scope)  # 2nd — blocked
        assert msgs[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_non_http_passthrough(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = RateLimitMiddleware(app, max_requests=10, window_seconds=60)
        await mw({"type": "websocket"}, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_rate_limit_headers_added(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=5, window_seconds=60)
        msgs = await _run_mw(mw, _make_scope(client=("2.3.4.5", 9000)))
        hd = {h[0] for h in msgs[0]["headers"]}
        assert b"x-ratelimit-limit" in hd
        assert b"x-ratelimit-remaining" in hd

    @pytest.mark.asyncio
    async def test_429_includes_retry_after(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=30)
        scope = _make_scope(client=("3.4.5.6", 9000))
        await _run_mw(mw, scope)
        msgs = await _run_mw(mw, scope)
        hd = dict(msgs[0]["headers"])
        assert b"retry-after" in hd
        assert hd[b"retry-after"] == b"30"

    @pytest.mark.asyncio
    async def test_429_ratelimit_remaining_is_zero(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        scope = _make_scope(client=("4.5.6.7", 9000))
        await _run_mw(mw, scope)
        msgs = await _run_mw(mw, scope)
        hd = dict(msgs[0]["headers"])
        assert hd[b"x-ratelimit-remaining"] == b"0"

    @pytest.mark.asyncio
    async def test_custom_key_func(self):
        """A custom key_func overrides the default IP-based key."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60, key_func=lambda s: "fixed")
        scope_a = _make_scope(client=("10.0.0.1", 9000))
        scope_b = _make_scope(client=("10.0.0.2", 9000))
        await _run_mw(mw, scope_a)
        msgs = await _run_mw(mw, scope_b)  # different IP, same key → blocked
        assert msgs[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_different_ips_tracked_independently(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        await _run_mw(mw, _make_scope(client=("5.5.5.5", 9000)))  # exhaust 5.5.5.5
        msgs = await _run_mw(mw, _make_scope(client=("6.6.6.6", 9000)))  # 6.6.6.6 still fresh
        assert msgs[0]["status"] == 200


# ---------------------------------------------------------------------------
# Default key extraction — tested via middleware behaviour (no protected access)
# ---------------------------------------------------------------------------


class TestRateLimitDefaultKey:
    @pytest.mark.asyncio
    async def test_client_tuple_used_as_key(self):
        """Two requests from the same client tuple share a counter."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        scope = _make_scope(client=("7.7.7.7", 9000))
        await _run_mw(mw, scope)
        msgs = await _run_mw(mw, scope)
        assert msgs[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_client_tuple_preferred_over_xff(self):
        """Client tuple must take priority over X-Forwarded-For to prevent IP spoofing."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        # First request uses client tuple "8.8.8.8"
        scope_real = _make_scope(
            client=("8.8.8.8", 9000),
            headers=[(b"x-forwarded-for", b"1.1.1.1")],
        )
        await _run_mw(mw, scope_real)
        # Second request from same tuple → blocked (proves tuple was key, not XFF)
        msgs = await _run_mw(mw, scope_real)
        assert msgs[0]["status"] == 429
        # Request from XFF IP "1.1.1.1" with no client tuple is still allowed
        scope_xff = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
            "client": None,
            "query_string": b"",
        }
        msgs_xff = await _run_mw(mw, scope_xff)
        assert msgs_xff[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_xff_fallback_when_no_client(self):
        """When client is None, X-Forwarded-For first IP is used."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"9.9.9.9, 10.0.0.1")],
            "client": None,
            "query_string": b"",
        }
        await _run_mw(mw, scope)
        msgs = await _run_mw(mw, scope)
        assert msgs[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_unknown_key_when_no_client_no_xff(self):
        """Requests with no client and no XFF share the 'unknown' bucket."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RateLimitMiddleware(app, max_requests=1, window_seconds=60)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": None,
            "query_string": b"",
        }
        await _run_mw(mw, scope)
        msgs = await _run_mw(mw, scope)
        assert msgs[0]["status"] == 429


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------


class TestRateLimitDecorator:
    @pytest.mark.asyncio
    async def test_decorator_allows_within_limit(self):
        @rate_limit(max_requests=5, window_seconds=60)
        async def handler(request):
            return "ok"

        assert await handler(_make_request("20.0.0.1")) == "ok"

    @pytest.mark.asyncio
    async def test_decorator_blocks_over_limit(self):
        @rate_limit(max_requests=1, window_seconds=60)
        async def handler(request):
            return "ok"

        await handler(_make_request("20.0.0.2"))
        with pytest.raises(TooManyRequests):
            await handler(_make_request("20.0.0.2"))

    @pytest.mark.asyncio
    async def test_decorator_includes_retry_after_in_exception(self):
        @rate_limit(max_requests=1, window_seconds=45)
        async def handler(request):
            return "ok"

        await handler(_make_request("20.0.0.3"))
        with pytest.raises(TooManyRequests) as exc_info:
            await handler(_make_request("20.0.0.3"))
        assert exc_info.value.headers.get("Retry-After") == "45"

    @pytest.mark.asyncio
    async def test_decorator_no_request_skips_check(self):
        """When no Request arg is found, rate limiting must be skipped."""

        @rate_limit(max_requests=1, window_seconds=60)
        async def handler():
            return "ok"

        assert await handler() == "ok"
        assert await handler() == "ok"  # not limited — no Request

    @pytest.mark.asyncio
    async def test_decorator_uses_client_ip(self):
        """Each unique client IP gets its own counter."""

        @rate_limit(max_requests=1, window_seconds=60)
        async def handler(request):
            return "ok"

        await handler(_make_request("20.0.0.4"))
        with pytest.raises(TooManyRequests):
            await handler(_make_request("20.0.0.4"))  # same IP — blocked
        assert await handler(_make_request("20.0.0.5")) == "ok"  # different IP — ok
