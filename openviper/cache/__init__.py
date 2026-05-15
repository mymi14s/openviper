from __future__ import annotations

from typing import Any

from openviper.cache.base import BaseCache
from openviper.cache.db_backend import DatabaseCache
from openviper.cache.memory import InMemoryCache
from openviper.cache.redis import RedisCache, redis_lib
from openviper.conf import settings
from openviper.utils.importlib import import_string

_cache_instances: dict[str, BaseCache] = {}


def get_cache(alias: str = "default") -> BaseCache:
    """Return the cache backend for the given alias, creating it if necessary.

    Instances are stored in ``_cache_instances`` and reused on subsequent calls.
    Raises ``ValueError`` for unknown non-default aliases.
    """
    if alias in _cache_instances:
        return _cache_instances[alias]
    caches_config = settings.CACHES
    if alias not in caches_config:
        if alias == "default":
            instance: BaseCache = InMemoryCache()
            _cache_instances[alias] = instance
            return instance
        raise ValueError(f"Cache alias {alias!r} not found in settings.CACHES")
    config = caches_config[alias]
    backend_path: str = config["BACKEND"]
    options: dict[str, Any] = config.get("OPTIONS", {})
    if backend_path == "openviper.cache.InMemoryCache":
        backend_cls: type[BaseCache] = InMemoryCache
    elif backend_path == "openviper.cache.RedisCache":
        backend_cls = RedisCache
    elif backend_path == "openviper.cache.DatabaseCache":
        backend_cls = DatabaseCache
    else:
        backend_cls = import_string(backend_path)
    instance = backend_cls(**options)
    _cache_instances[alias] = instance
    return instance


__all__ = [
    "BaseCache",
    "DatabaseCache",
    "InMemoryCache",
    "RedisCache",
    "get_cache",
    "redis_lib",
]
