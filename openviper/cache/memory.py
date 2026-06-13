"""In-memory cache backend using a dict with TTL support."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from openviper.cache.base import BaseCache
from openviper.cache.validation import validate_cache_key
from openviper.conf import settings

DEFAULT_CACHE_TTL: int = 300


def get_default_ttl() -> int:
    """Return the default TTL from CACHES config or legacy CACHE_TTL setting."""
    caches = getattr(settings, "CACHES", {})
    if isinstance(caches, Mapping):
        default_config = caches.get("default")
        if isinstance(default_config, Mapping):
            options = default_config.get("OPTIONS")
            if isinstance(options, Mapping):
                ttl = options.get("ttl") or options.get("TTL")
                if isinstance(ttl, int):
                    return ttl
    cache_ttl = getattr(settings, "CACHE_TTL", None)
    if isinstance(cache_ttl, int):
        return cache_ttl
    return DEFAULT_CACHE_TTL


class InMemoryCache(BaseCache):
    """Simple in-memory cache implementation using a dictionary.

    Thread-safe for concurrent async access via an ``asyncio.Lock``.
    When no ``ttl`` is provided to ``set()``, the TTL from
    ``CACHES['default']['OPTIONS']['ttl']`` is used (default 300 seconds).
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the in-memory store and async lock.

        Accepts and ignores extra keyword arguments so that OPTIONS
        like ``ttl`` can be present in the CACHES config without
        causing ``TypeError``.
        """
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
            ttl = get_default_ttl()
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
            result: list[str] = []
            for key, (_, exp) in self._data.items():
                if exp is not None and now >= exp:
                    del self._data[key]
                elif not prefix or key.startswith(prefix):
                    result.append(key)
            return result
