"""Redis-backed cache implementation using redis.asyncio with orjson serialization."""

from __future__ import annotations

from typing import Any

import orjson

from openviper.cache.base import BaseCache, deserialize_cache_value
from openviper.cache.validation import validate_cache_key

DEFAULT_KEY_PREFIX: str = "ov:cache:"

try:
    import redis.asyncio as redis_lib
except ImportError:
    redis_lib = None  # type: ignore[assignment,unused-ignore]


class RedisCache(BaseCache):
    """Redis-backed cache using redis.asyncio with orjson serialization.

    Requires the ``redis`` package to be installed.
    Install it with: ``pip install redis``

    All keys are prefixed with ``key_prefix`` (default ``"ov:cache:"``) to
    isolate this cache from other data in the same Redis database.  The
    ``clear()`` method only deletes keys matching the prefix - it never calls
    ``FLUSHDB``.
    """

    def __init__(self, *, key_prefix: str = DEFAULT_KEY_PREFIX, **kwargs: Any) -> None:
        """Initialise the Redis cache with an optional key prefix."""
        if redis_lib is None:
            msg = (
                "The 'redis' package is required to use RedisCache. "
                "Install it with: pip install redis"
            )
            raise ImportError(msg)
        self._prefix: str = key_prefix
        self._client: redis_lib.Redis = redis_lib.Redis(**kwargs)

    def prefixed(self, key: str) -> str:
        """Return *key* with the configured prefix prepended."""
        return f"{self._prefix}{key}"

    async def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Fetch a value from the cache, returning *default* on miss."""
        validate_cache_key(key)
        value = await self._client.get(self.prefixed(key))
        if value is None:
            return default
        return deserialize_cache_value(value, key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache with an optional TTL."""
        validate_cache_key(key)
        if isinstance(value, (dict, list)):
            serialized: bytes = orjson.dumps(value)
        else:
            serialized = value
        await self._client.set(self.prefixed(key), serialized, ex=ttl)

    async def delete(self, key: str) -> None:
        """Remove a value from the cache."""
        validate_cache_key(key)
        await self._client.delete(self.prefixed(key))

    async def clear(self) -> None:
        """Delete only keys that match this cache's prefix.

        Uses ``SCAN`` to iterate matching keys and ``UNLINK`` for non-blocking
        removal.  This is safe for shared Redis instances - it never calls
        ``FLUSHDB``.
        """
        cursor: int = 0
        pattern = f"{self._prefix}*"
        while True:
            cursor, keys = await self._client.scan(cursor, match=pattern, count=200)
            if keys:
                await self._client.unlink(*keys)
            if cursor == 0:
                break

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        validate_cache_key(key)
        return bool(await self._client.exists(self.prefixed(key)))
