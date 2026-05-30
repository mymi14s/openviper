"""In-memory cache backend using a dict with TTL support."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from openviper.cache.base import BaseCache
from openviper.cache.validation import validate_cache_key
from openviper.conf import settings


class InMemoryCache(BaseCache):
    """Simple in-memory cache implementation using a dictionary.

    Thread-safe for concurrent async access via an ``asyncio.Lock``.
    When no ``ttl`` is provided to ``set()``, ``settings.CACHE_TTL`` is
    used as the default.
    """

    def __init__(self) -> None:
        """Initialise the in-memory store and async lock."""
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Fetch a value from the cache, returning *default* on miss."""
        validate_cache_key(key)
        async with self._lock:
            if key not in self._data:
                return default

            value, expiry = self._data[key]
            if expiry is not None and time.time() >= expiry:
                del self._data[key]
                return default

            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache with an optional TTL."""
        validate_cache_key(key)
        if ttl is None:
            ttl = int(cast("int", settings.CACHE_TTL))
        expiry = time.time() + ttl
        async with self._lock:
            self._data[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        """Remove a value from the cache."""
        validate_cache_key(key)
        async with self._lock:
            if key in self._data:
                del self._data[key]

    async def clear(self) -> None:
        """Remove all values from the cache."""
        async with self._lock:
            self._data.clear()

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        validate_cache_key(key)
        async with self._lock:
            if key not in self._data:
                return False

            _, expiry = self._data[key]
            if expiry is not None and time.time() >= expiry:
                del self._data[key]
                return False

            return True

    async def keys(self, prefix: str = "") -> list[str]:
        """Return all cache keys, optionally filtered by prefix."""
        async with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if exp is not None and now >= exp]
            for k in expired:
                del self._data[k]
            if prefix:
                return [k for k in self._data if k.startswith(prefix)]
            return list(self._data)
