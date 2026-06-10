"""Memcached-backed cache implementation using aiomcache with orjson serialization."""

from __future__ import annotations

import logging
from typing import Any

import orjson

from openviper.cache.base import BaseCache
from openviper.cache.validation import validate_cache_key

logger = logging.getLogger(__name__)

DEFAULT_KEY_PREFIX: str = "ov:cache:"

try:
    import aiomcache as mcache_lib
except ImportError:
    mcache_lib = None  # type: ignore[assignment,unused-ignore]


class MemcachedCache(BaseCache):
    """Memcached-backed cache using aiomcache with orjson serialization.

    Requires the ``aiomcache`` package to be installed.
    Install it with: ``pip install aiomcache``

    All keys are prefixed with ``key_prefix`` (default ``"ov:cache:"``) to
    isolate this cache from other data in the same Memcached instance.
    Memcached has a native TTL mechanism and a maximum value size of 1 MB.
    """

    def __init__(
        self,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        host: str = "localhost",
        port: int = 11211,
        **kwargs: Any,
    ) -> None:
        """Initialise the Memcached cache with connection parameters."""
        if mcache_lib is None:
            msg = (
                "The 'aiomcache' package is required to use MemcachedCache. "
                "Install it with: pip install aiomcache"
            )
            raise ImportError(msg)
        self._prefix: str = key_prefix
        self._client: mcache_lib.Client = mcache_lib.Client(host=host, port=port, **kwargs)

    def _prefixed(self, key: str) -> str:
        """Return *key* with the configured prefix prepended."""
        return f"{self._prefix}{key}"

    async def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Fetch a value from the cache, returning *default* on miss."""
        validate_cache_key(key)
        value = await self._client.get(self._prefixed(key).encode())
        if value is None:
            return default
        try:
            return orjson.loads(value)
        except ValueError, TypeError:
            logger.debug("Failed to deserialize cached value for key %r", key, exc_info=True)
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache with an optional TTL in seconds."""
        validate_cache_key(key)
        if isinstance(value, (dict, list)):
            serialized: bytes = orjson.dumps(value)
        else:
            serialized = orjson.dumps(value)
        await self._client.set(self._prefixed(key).encode(), serialized, exptime=ttl or 0)

    async def delete(self, key: str) -> None:
        """Remove a value from the cache."""
        validate_cache_key(key)
        await self._client.delete(self._prefixed(key).encode())

    async def clear(self) -> None:
        """Flush all keys in the Memcached instance.

        Memcached does not support prefix-based iteration, so this calls
        ``flush_all`` which clears the entire instance. Use separate
        Memcached instances or key prefixes to isolate data.
        """
        await self._client.flush_all()

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        validate_cache_key(key)
        value = await self._client.get(self._prefixed(key).encode())
        return value is not None


__all__ = ["MemcachedCache"]
