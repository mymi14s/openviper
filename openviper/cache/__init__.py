from __future__ import annotations

from openviper.cache.base import BaseCache
from openviper.cache.memory import InMemoryCache
from openviper.cache.redis import RedisCache
from openviper.conf import settings
from openviper.utils.importlib import import_string

_cache_instance: BaseCache | None = None


def get_cache() -> BaseCache:
    """Entry point to get the configured cache backend.

    Returns the cache instance according to `settings.CACHE_BACKEND`.
    The instance is cached for subsequent calls.
    """
    global _cache_instance

    if _cache_instance is not None:
        return _cache_instance

    backend = settings.CACHE_BACKEND

    if backend == "memory":
        _cache_instance = InMemoryCache()
    elif backend == "redis":
        redis_url = settings.CACHE_URL or "redis://localhost:6379"
        _cache_instance = RedisCache(url=redis_url)
    elif "." in backend:
        # Load custom backend class via dotted path
        cache_cls = import_string(backend)
        _cache_instance = cache_cls()
    else:
        # Default or unknown backend, fallback to memory
        _cache_instance = InMemoryCache()

    return _cache_instance


__all__ = ["InMemoryCache", "get_cache", "BaseCache", "RedisCache"]
