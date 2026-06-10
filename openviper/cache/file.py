"""File-system-backed cache implementation using async I/O with orjson serialization."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

import orjson

from openviper.cache.base import BaseCache
from openviper.cache.validation import validate_cache_key

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR: str = ".cache/openviper"
DEFAULT_KEY_PREFIX: str = "ov:cache:"

__all__ = ["FileCache", "safe_filename"]


def safe_filename(key: str) -> str:
    """Convert a cache key into a safe filesystem path component.

    Hex encoding eliminates directory traversal and filesystem-reserved
    character risks by producing a deterministic, flat filename.
    """
    return key.encode().hex()


class FileCache(BaseCache):
    """File-system-backed cache using async I/O with orjson serialization.

    Stores each cache entry as a separate file under ``cache_dir``.
    Each file contains an orjson-serialized dict with ``value``, ``expiry``,
    and ``key`` fields.  Expired entries are lazily removed on access.

    Suitable for single-server deployments or development environments
    where Redis/Memcached are not available.  Not recommended for
    multi-server setups because the cache directory is local to each node.
    """

    def __init__(
        self,
        *,
        cache_dir: str = DEFAULT_CACHE_DIR,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        **kwargs: Any,
    ) -> None:
        """Initialise the file cache with a directory path and optional prefix."""
        self._cache_dir: Path = Path(cache_dir)
        self._prefix: str = key_prefix
        self._lock: asyncio.Lock = asyncio.Lock()

    def _filepath(self, key: str) -> Path:
        """Return the file path for a given cache key."""
        filename = safe_filename(f"{self._prefix}{key}")
        return self._cache_dir / filename

    async def _ensure_dir(self) -> None:
        """Create the cache directory if it does not exist."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self._cache_dir.mkdir(parents=True, exist_ok=True))

    async def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Fetch a value from the cache, returning *default* on miss."""
        validate_cache_key(key)
        filepath = self._filepath(key)
        loop = asyncio.get_running_loop()

        try:
            raw: bytes = await loop.run_in_executor(None, filepath.read_bytes)
        except FileNotFoundError:
            return default

        try:
            entry: dict[str, Any] = orjson.loads(raw)
        except ValueError, TypeError:
            logger.debug("Failed to deserialize cached file for key %r", key, exc_info=True)
            return default

        expiry = entry.get("expiry")
        if expiry is not None and time.time() >= expiry:
            await self.delete(key)
            return default

        return entry.get("value", default)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache with an optional TTL in seconds."""
        validate_cache_key(key)
        await self._ensure_dir()
        filepath = self._filepath(key)
        expiry: float | None = time.time() + ttl if ttl is not None else None
        entry: dict[str, Any] = {"value": value, "expiry": expiry, "key": key}
        serialized: bytes = orjson.dumps(entry)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: filepath.write_bytes(serialized))

    async def delete(self, key: str) -> None:
        """Remove a value from the cache."""
        validate_cache_key(key)
        filepath = self._filepath(key)
        loop = asyncio.get_running_loop()
        with contextlib.suppress(FileNotFoundError):
            await loop.run_in_executor(None, filepath.unlink, True)

    async def clear(self) -> None:
        """Remove all cache files in the cache directory."""
        loop = asyncio.get_running_loop()

        def _clear_dir() -> None:
            if not self._cache_dir.exists():
                return
            for f in self._cache_dir.iterdir():
                with contextlib.suppress(OSError):
                    f.unlink()

        await loop.run_in_executor(None, _clear_dir)

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache and is not expired."""
        validate_cache_key(key)
        filepath = self._filepath(key)
        loop = asyncio.get_running_loop()

        try:
            raw: bytes = await loop.run_in_executor(None, filepath.read_bytes)
        except FileNotFoundError:
            return False

        try:
            entry: dict[str, Any] = orjson.loads(raw)
        except ValueError, TypeError:
            return False

        expiry = entry.get("expiry")
        if expiry is not None and time.time() >= expiry:
            await self.delete(key)
            return False

        return True
