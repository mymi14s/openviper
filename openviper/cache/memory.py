from __future__ import annotations

import time
from typing import Any

from openviper.cache.base import BaseCache
from openviper.conf import settings


class InMemoryCache(BaseCache):
    """Simple in-memory cache implementation using a dictionary."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        if key not in self._data:
            return default

        value, expiry = self._data[key]
        if expiry is not None and time.time() >= expiry:
            del self._data[key]
            return default

        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl is None:
            ttl = settings.CACHE_TTL

        expiry = time.time() + ttl if ttl is not None else None
        self._data[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        if key in self._data:
            del self._data[key]

    async def clear(self) -> None:
        self._data.clear()

    async def has_key(self, key: str) -> bool:
        if key not in self._data:
            return False

        _, expiry = self._data[key]
        if expiry is not None and time.time() >= expiry:
            del self._data[key]
            return False

        return True

    async def keys(self, prefix: str = "") -> list[str]:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp is not None and now >= exp]
        for k in expired:
            del self._data[k]
        if prefix:
            return [k for k in self._data if k.startswith(prefix)]
        return list(self._data)
