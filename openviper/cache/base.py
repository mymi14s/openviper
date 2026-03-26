from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCache(ABC):
    """Abstract base class for all cache backends."""

    @abstractmethod
    async def get(self, key: str, default: Any = None) -> Any:
        """Fetch a value from the cache.

        Args:
            key: The cache key.
            default: Value to return if the key is not found.
        """
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in the cache.

        Args:
            key: The cache key.
            value: The value to store.
            ttl: Time-to-live in seconds. If None, uses default TTL.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a value from the cache.

        Args:
            key: The cache key.
        """
        raise NotImplementedError

    @abstractmethod
    async def clear(self) -> None:
        """Remove all values from the cache."""
        raise NotImplementedError

    @abstractmethod
    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key: The cache key.
        """
        raise NotImplementedError

    async def keys(self, prefix: str = "") -> list[str]:
        """Return all cache keys, optionally filtered by prefix.

        Default implementation returns an empty list.  Backends that can
        efficiently enumerate keys should override this method.

        Args:
            prefix: If non-empty, only keys starting with this string are returned.
        """
        return []
