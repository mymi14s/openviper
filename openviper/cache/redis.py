"""Redis-backed cache implementation using redis.asyncio with orjson serialization."""

from __future__ import annotations

import logging
from typing import Any

import orjson

from openviper.cache.base import BaseCache

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis_lib
except ImportError:
    redis_lib = None  # type: ignore[assignment]


class RedisCache(BaseCache):
    """Redis-backed cache using redis.asyncio with orjson serialization.

    Requires the ``redis`` package to be installed.
    Install it with: ``pip install redis``
    """

    def __init__(self, **kwargs: Any) -> None:
        if redis_lib is None:
            raise ImportError(
                "The 'redis' package is required to use RedisCache. "
                "Install it with: pip install redis"
            )
        self._client = redis_lib.Redis(**kwargs)

    async def get(self, key: str, default: Any = None) -> Any:
        value = await self._client.get(key)
        if value is None:
            return default
        try:
            return orjson.loads(value)
        except Exception:
            logger.debug("Failed to deserialize cached value for key", exc_info=True)
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if isinstance(value, (dict, list)):
            serialized: Any = orjson.dumps(value)
        else:
            serialized = value
        await self._client.set(key, serialized, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def clear(self) -> None:
        await self._client.flushdb()

    async def has_key(self, key: str) -> bool:
        return bool(await self._client.exists(key))
