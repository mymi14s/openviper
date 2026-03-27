from __future__ import annotations

import json
from typing import Any

from openviper.cache.base import BaseCache
from openviper.conf import settings

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # type: ignore[assignment]


class RedisCache(BaseCache):
    """Redis-backed cache implementation.

    Requires the `redis` package to be installed.
    """

    def __init__(self, url: str | None = None, **kwargs: Any) -> None:
        if redis is None:
            raise ImportError(
                "The 'redis' Python package is required for RedisCache. "
                "Install it with: pip install redis"
            )
        if url is None:
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379")
        self.client = redis.Redis.from_url(url, **kwargs)

    async def get(self, key: str, default: Any = None) -> Any:
        value = await self.client.get(key)
        if value is None:
            return default
        try:
            # We serialize to JSON to maintain types like dict/list
            return json.loads(value)
        except json.JSONDecodeError:
            # Fallback to returning raw string if it wasn't valid JSON
            return value.decode("utf-8") if isinstance(value, bytes) else value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        serialized = json.dumps(value)
        await self.client.set(key, serialized, ex=ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def has_key(self, key: str) -> bool:
        exists = await self.client.exists(key)
        return bool(exists)

    async def clear(self) -> None:
        await self.client.flushdb()
