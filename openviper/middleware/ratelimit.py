"""Token-bucket / sliding-window rate limiting middleware and decorator.

The sliding window counter uses 256 independent :class:`asyncio.Lock` objects
(one per hash stripe) instead of a single global lock, reducing contention
by ~256x under concurrent load.
"""

from __future__ import annotations

import asyncio
import dataclasses
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Final, ParamSpec, Protocol, TypeVar, cast

from openviper.conf import settings
from openviper.exceptions import TooManyRequests
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.middleware.base import ASGIApp, BaseMiddleware

if TYPE_CHECKING:
    from openviper.http.types import ASGIMessage, ASGIReceive, ASGIScope, ASGISend

try:
    from redis.asyncio import Redis as _RedisFactory

    REDIS_AVAILABLE: bool = True
    redis_asyncio_module: RedisAsyncioModuleProtocol = cast(
        "RedisAsyncioModuleProtocol", _RedisFactory
    )
except ImportError:
    REDIS_AVAILABLE = False
    redis_asyncio_module: RedisAsyncioModuleProtocol | None = None

# Power-of-two striping keeps lock selection cheap on the request path.
STRIPE_COUNT: Final[int] = 256
P = ParamSpec("P")
R = TypeVar("R")
type RateLimitCounter = SlidingWindowCounter | RedisWindowCounter


class RedisPipelineProtocol(Protocol):
    """Structural subset of the Redis async pipeline used here."""

    def zremrangebyscore(self, name: str, min: int, max: float) -> object: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> object: ...

    def zcard(self, name: str) -> object: ...

    def expire(self, name: str, time: int) -> object: ...

    async def execute(self) -> list[object]: ...


class RedisClientProtocol(Protocol):
    """Structural subset of the Redis async client used here."""

    def pipeline(self) -> RedisPipelineProtocol: ...

    async def zrem(self, name: str, *values: str) -> object: ...


class RedisFactoryProtocol(Protocol):
    """Factory interface exposed by ``redis.asyncio.Redis``."""

    def from_url(self, url: str) -> RedisClientProtocol: ...


class RedisAsyncioModuleProtocol(Protocol):
    """Module interface needed from ``redis.asyncio``."""

    Redis: RedisFactoryProtocol


class RedisWindowCounter:
    """Sliding-window rate counter backed by a Redis sorted set.

    Each key maps to a sorted set whose members are unique request tokens
    and whose scores are Unix timestamps.  Stale entries (outside the
    current window) are pruned atomically via ZREMRANGEBYSCORE.

    Requires ``redis>=7.4.0`` (``pip install redis``).
    """

    __slots__ = ("max_requests", "window", "_client")

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if not REDIS_AVAILABLE or redis_asyncio_module is None:
            raise ImportError(
                "redis package is required for RATE_LIMIT_BACKEND='redis'. "
                "Install it with: pip install redis"
            )
        self.max_requests = max_requests
        self.window = window_seconds
        url: str = cast("str", settings.CACHE_URL) or "redis://localhost:6379"
        self._client: RedisClientProtocol = redis_asyncio_module.Redis.from_url(url)

    async def is_allowed(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` for *key* using a Redis sorted set."""
        now = time.time()
        cutoff = now - self.window
        rk = f"rl:{key}"
        token = secrets.token_hex(8)
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(rk, 0, cutoff)
        pipe.zadd(rk, {token: now})
        pipe.zcard(rk)
        pipe.expire(rk, int(self.window) + 1)
        results = await pipe.execute()
        count = int(results[2])
        if count > self.max_requests:
            await self._client.zrem(rk, token)
            return False, 0
        return True, self.max_requests - count


@dataclasses.dataclass(slots=True)
class Bucket:
    """Sliding-window state for a single rate-limit key."""

    timestamps: deque[float]
    last_access: float


class SlidingWindowCounter:
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
        "_last_evicts",
        "_evict_interval",
    )

    def __init__(
        self, max_requests: int, window_seconds: float, evict_interval: float = 300.0
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._buckets: list[dict[str, Bucket]] = [{} for _ in range(STRIPE_COUNT)]
        self._locks: list[asyncio.Lock] = [asyncio.Lock() for _ in range(STRIPE_COUNT)]
        self._last_evicts: list[float] = [0.0] * STRIPE_COUNT
        self._evict_interval: float = evict_interval

    async def is_allowed(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` for *key*.

        Acquires only the lock for ``hash(key) & 255`` - concurrent requests
        for keys in different stripes proceed without contention.
        """
        now = time.monotonic()
        stripe = hash(key) & (STRIPE_COUNT - 1)
        cutoff = now - self.window

        async with self._locks[stripe]:
            stripe_map = self._buckets[stripe]

            # Per-stripe eviction avoids cross-key contention under load.
            if now - self._last_evicts[stripe] > self._evict_interval:
                stale_cutoff = now - 2.0 * self.window
                stale_keys = [
                    stale_key
                    for stale_key, bucket in stripe_map.items()
                    if bucket.last_access < stale_cutoff
                ]
                for stale_key in stale_keys:
                    del stripe_map[stale_key]
                self._last_evicts[stripe] = now

            bucket = stripe_map.get(key)
            if bucket is None:
                bucket = Bucket(timestamps=deque(), last_access=now)
                stripe_map[key] = bucket

            while bucket.timestamps and bucket.timestamps[0] < cutoff:
                bucket.timestamps.popleft()

            bucket.last_access = now

            if len(bucket.timestamps) >= self.max_requests:
                return False, 0

            bucket.timestamps.append(now)
            return True, self.max_requests - len(bucket.timestamps)


class RateLimitMiddleware(BaseMiddleware):
    """ASGI rate limiting middleware using a per-key sliding window.

    Configurable via ``RATE_LIMIT_REQUESTS``, ``RATE_LIMIT_WINDOW``,
    and ``RATE_LIMIT_BY`` settings or constructor arguments.
    Adds ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, and
    ``Retry-After`` headers to every response.
    """

    __slots__ = ("max_requests", "window_seconds", "counter", "_key_func")

    def __init__(
        self,
        app: ASGIApp,
        max_requests: int | None = None,
        window_seconds: float | None = None,
        key_func: Callable[[ASGIScope], str] | None = None,
    ) -> None:
        super().__init__(app)
        self.max_requests: int = (
            max_requests
            if max_requests is not None
            else getattr(settings, "RATE_LIMIT_REQUESTS", 2000)
        )
        self.window_seconds: float = (
            window_seconds
            if window_seconds is not None
            else float(getattr(settings, "RATE_LIMIT_WINDOW", 60))
        )
        self.counter: RateLimitCounter = SlidingWindowCounter(
            self.max_requests, self.window_seconds
        )
        backend = getattr(settings, "RATE_LIMIT_BACKEND", "memory")
        if backend == "redis":
            self.counter = RedisWindowCounter(self.max_requests, self.window_seconds)
        if key_func is not None:
            self._key_func = key_func
        else:
            by = getattr(settings, "RATE_LIMIT_BY", "ip")
            if by == "user":
                self._key_func = RateLimitMiddleware.user_key
            elif by == "path":
                self._key_func = RateLimitMiddleware.path_key
            else:
                self._key_func = RateLimitMiddleware.default_key

    @staticmethod
    def default_key(scope: ASGIScope) -> str:
        """Key = client IP address.

        Uses the ASGI ``client`` tuple (set by the server from the actual
        TCP connection).  ``X-Forwarded-For`` is intentionally NOT used
        because it can be spoofed by untrusted clients to bypass rate
        limits.  Deployments behind a trusted reverse proxy should configure
        the proxy to set the ASGI ``client`` tuple from the real IP.
        """
        client = scope.get("client")
        if client:
            host, _port = cast("tuple[str, int]", client)
            return host
        return "unknown"

    @staticmethod
    def user_key(scope: ASGIScope) -> str:
        """Key = authenticated user PK, falling back to IP for anonymous requests."""
        user = scope.get("user")
        if user is not None and not getattr(user, "is_anonymous", True):
            uid = getattr(user, "pk", None) or getattr(user, "id", None) or str(user)
            return f"user:{uid}"
        return RateLimitMiddleware.default_key(scope)

    @staticmethod
    def path_key(scope: ASGIScope) -> str:
        """Key = (client IP, request path) - rate limits each endpoint independently."""
        ip = RateLimitMiddleware.default_key(scope)
        path = cast("str", scope.get("path", "/"))
        return f"path:{ip}:{path}"

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = self._key_func(scope)
        allowed, remaining = await self.counter.is_allowed(key)

        if not allowed:
            reset_epoch = int(time.time() + self.window_seconds)
            response = JSONResponse(
                {
                    "detail": "Too many requests",
                    "retry_after": int(self.window_seconds),
                },
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_epoch),
                    "Retry-After": str(int(self.window_seconds)),
                },
            )
            await response(scope, receive, send)
            return

        limit_b = str(self.max_requests).encode()
        remaining_b = str(remaining).encode()
        reset_b = str(int(time.time() + self.window_seconds)).encode()

        async def send_with_headers(message: ASGIMessage) -> None:
            if message["type"] == "http.response.start":
                headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                headers = list(headers)
                headers.append((b"x-ratelimit-limit", limit_b))
                headers.append((b"x-ratelimit-remaining", remaining_b))
                headers.append((b"x-ratelimit-reset", reset_b))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def rate_limit(
    max_requests: int = 60, window_seconds: float = 60.0
) -> Callable[[Callable[..., Awaitable[R]]], Callable[..., Awaitable[R]]]:
    """Decorator to apply per-view rate limiting based on client IP."""
    counter = SlidingWindowCounter(max_requests, window_seconds)

    def decorator(func: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> R:
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request_candidate = kwargs.get("request")
                if isinstance(request_candidate, Request):
                    request = request_candidate

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
