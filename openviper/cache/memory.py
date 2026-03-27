from __future__ import annotations

import time
from typing import Any

from openviper.cache.base import BaseCache
from openviper.conf import settings


class InMemoryCache(BaseCache):
    """Simple in-memory cache implementation using a dictionary."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        if key not in self._cache:
            return default

        value, expiry = self._cache[key]
        if expiry is not None and time.time() > expiry:
            del self._cache[key]
            return default

        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl is None:
            ttl = settings.CACHE_TTL

        expiry = time.time() + ttl if ttl is not None else None
        self._cache[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]

    async def clear(self) -> None:
        self._cache.clear()

    async def has_key(self, key: str) -> bool:
        if key not in self._cache:
            return False

        _, expiry = self._cache[key]
        if expiry is not None and time.time() > expiry:
            del self._cache[key]
            return False

        return True

    async def keys(self, prefix: str = "") -> list[str]:
        now = time.time()
        expired = [k for k, (_, exp) in self._cache.items() if exp is not None and now > exp]
        for k in expired:
            del self._cache[k]
        if prefix:
            return [k for k in self._cache if k.startswith(prefix)]
        return list(self._cache)
