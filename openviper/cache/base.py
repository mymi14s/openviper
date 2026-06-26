"""Abstract base class defining the async cache interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import orjson

from openviper.cache.validation import validate_cache_key

logger = logging.getLogger("openviper.cache")


def deserialize_cache_value(raw: bytes | str, key: str) -> Any:
    """Deserialize a cached value from JSON bytes, returning *raw* on failure.

    All cache backends use orjson for serialization; this helper
    centralises the ``orjson.loads`` call and the graceful fallback
    so each backend does not repeat the try/except boilerplate.
    """
    try:
        return orjson.loads(raw)
    except (ValueError, TypeError):
        logger.debug("Failed to deserialize cached value for key %r", key, exc_info=True)
        return raw


class BaseCache(ABC):
    """Abstract base class for all cache backends.

    All concrete backends **must** call ``validate_cache_key(key)`` before
    performing any operation.  This ensures keys are safe for the underlying
    store and prevents injection or protocol-level errors.
    """

    @abstractmethod
    async def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Fetch a value from the cache.

        Args:
            key: The cache key (validated by the base class).
            default: Value to return if the key is not found.

        """
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache.

        Args:
            key: The cache key (validated by the base class).
            value: The value to store.
            ttl: Time-to-live in seconds. ``None`` means no expiry.

        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a value from the cache.

        Args:
            key: The cache key (validated by the base class).

        """
        raise NotImplementedError

    @abstractmethod
    async def clear(self) -> None:
        """Remove all values from the cache."""
        raise NotImplementedError

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Default implementation calls get() and checks for None.
        Backends that can more efficiently check key existence should override.

        Args:
            key: The cache key (validated by the base class).

        """
        validate_cache_key(key)
        return await self.get(key) is not None

    async def keys(self, prefix: str = "") -> list[str]:  # noqa: ARG002
        """Return all cache keys, optionally filtered by prefix.

        Default implementation returns an empty list.  Backends that can
        efficiently enumerate keys should override this method.

        Args:
            prefix: If non-empty, only keys starting with this string are returned.

        """
        return []

    async def close(self) -> None:
        """Release backend resources (connections, file handles).

        Backends that hold persistent connections should override this
        method to ensure clean shutdown. The default implementation is
        a no-op for backends that do not own connections.
        """
        return
