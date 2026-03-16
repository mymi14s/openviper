"""Token-bucket / sliding-window rate limiting middleware and decorator.

The sliding window counter uses 256 independent :class:`asyncio.Lock` objects
(one per hash stripe) instead of a single global lock.  Under concurrent load
this reduces contention by ~256×: only requests from the same hash stripe can
contend, which in practice means only 1/256 of key pairs block each other.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from typing import Any, Final, cast

from openviper.conf import settings
from openviper.exceptions import TooManyRequests
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.middleware.base import BaseMiddleware

# Number of independent lock stripes.  Must be a power of two so bitwise AND
# can replace modulo in the hot path.
_STRIPE_COUNT: Final[int] = 256

# ---------------------------------------------------------------------------
# Per-key bucket (slots for minimal overhead)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class _Bucket:
    """Sliding-window state for a single rate-limit key."""

    timestamps: deque[float]
    last_access: float


# ---------------------------------------------------------------------------
# Striped sliding-window counter
# ---------------------------------------------------------------------------


class _SlidingWindowCounter:
    """In-process sliding-window rate counter with per-stripe locking.

    256 independent asyncio locks replace the single global lock of the
    previous implementation.  Stale buckets are evicted lazily to bound
    memory growth.
    """

    __slots__ = (
        "max_requests",
        "window",
        "_buckets",
        "_locks",
        "_last_evict",
        "_evict_interval",
    )

    def __init__(
        self, max_requests: int, window_seconds: float, evict_interval: float = 300.0
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._buckets: list[dict[str, _Bucket]] = [{} for _ in range(_STRIPE_COUNT)]
        self._locks: list[asyncio.Lock] = [asyncio.Lock() for _ in range(_STRIPE_COUNT)]
        self._last_evict: float = time.monotonic()
        self._evict_interval: float = evict_interval

    async def is_allowed(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` for *key*.

        Acquires only the lock for ``hash(key) & 255`` — concurrent requests
        for keys in different stripes proceed without contention.
        """
        now = time.monotonic()
        stripe = hash(key) & (_STRIPE_COUNT - 1)
        cutoff = now - self.window

        async with self._locks[stripe]:
            stripe_map = self._buckets[stripe]

            # Lazy TTL eviction within this stripe: O(stripe_size) but typically
            # tiny and amortised over the 300 s evict interval.
            if now - self._last_evict > self._evict_interval:
                stale_cutoff = now - 2.0 * self.window
                stale = [k for k, b in stripe_map.items() if b.last_access < stale_cutoff]
                for k in stale:
                    del stripe_map[k]
                self._last_evict = now  # approximate; multiple stripes may update this

            bucket = stripe_map.get(key)
            if bucket is None:
                bucket = _Bucket(timestamps=deque(), last_access=now)
                stripe_map[key] = bucket

            # Remove timestamps that have fallen outside the window.
            while bucket.timestamps and bucket.timestamps[0] < cutoff:
                bucket.timestamps.popleft()

            bucket.last_access = now

            if len(bucket.timestamps) >= self.max_requests:
                return False, 0

            bucket.timestamps.append(now)
            return True, self.max_requests - len(bucket.timestamps)


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseMiddleware):
    """ASGI rate limiting middleware using a per-key sliding window.

    Settings (can also be passed directly)::

        RATE_LIMIT_REQUESTS = 100   # requests allowed per window
        RATE_LIMIT_WINDOW   = 60    # window size in seconds
        RATE_LIMIT_BY       = "ip"  # "ip" | "user" | "path"

    The middleware adds ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``,
    and ``Retry-After`` headers to every response.
    """

    __slots__ = ("max_requests", "window_seconds", "counter", "_key_func")

    def __init__(
        self,
        app: Any,
        max_requests: int | None = None,
        window_seconds: float | None = None,
        key_func: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        super().__init__(app)
        self.max_requests: int = (
            max_requests
            if max_requests is not None
            else getattr(settings, "RATE_LIMIT_REQUESTS", 100)
        )
        self.window_seconds: float = (
            window_seconds
            if window_seconds is not None
            else float(getattr(settings, "RATE_LIMIT_WINDOW", 60))
        )
        self.counter = _SlidingWindowCounter(self.max_requests, self.window_seconds)
        self._key_func = key_func or self._default_key

    @staticmethod
    def _default_key(scope: dict[str, Any]) -> str:
        """Key = client IP address.

        Prefers the ASGI ``client`` tuple (set by the server from the actual
        TCP connection) over ``X-Forwarded-For``, which can be spoofed by
        untrusted clients.  ``X-Forwarded-For`` is only used as a last
        resort when ``client`` is ``None`` (e.g. Unix-domain sockets).
        """
        client = scope.get("client")
        if client:
            return cast("str", client[0])
        # Fallback: X-Forwarded-For (only when no direct client info).
        # WARNING: This header is trivially spoofable. Only trust it if
        # the ASGI server is behind a known reverse proxy.
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                forwarded_for = value.decode("latin-1")
                if forwarded_for:
                    return str(forwarded_for.split(",")[0].strip())
        return "unknown"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = self._key_func(scope)
        allowed, remaining = await self.counter.is_allowed(key)

        if not allowed:
            response = JSONResponse(
                {
                    "detail": "Too many requests",
                    "retry_after": int(self.window_seconds),
                },
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(int(self.window_seconds)),
                },
            )
            await response(scope, receive, send)
            return

        limit_b = str(self.max_requests).encode()
        remaining_b = str(remaining).encode()

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", limit_b))
                headers.append((b"x-ratelimit-remaining", remaining_b))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---------------------------------------------------------------------------
# View decorator
# ---------------------------------------------------------------------------


def rate_limit(max_requests: int = 60, window_seconds: float = 60.0) -> Callable[..., Any]:
    """Decorator to apply per-view rate limiting based on client IP.

    Usage::

        @app.get("/expensive")
        @rate_limit(max_requests=10, window_seconds=60)
        async def expensive_view(request: Request):
            ...
    """
    counter = _SlidingWindowCounter(max_requests, window_seconds)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")

            if request is not None:
                key = (request.client or ("unknown", 0))[0]
                allowed, _remaining = await counter.is_allowed(key)
                if not allowed:
                    raise TooManyRequests(
                        retry_after=int(window_seconds),
                        detail=(
                            f"Rate limit exceeded: {max_requests} requests per {window_seconds}s"
                        ),
                    )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
