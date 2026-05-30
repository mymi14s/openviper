"""Cache framework providing a unified async interface for multiple backends."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, cast

from openviper.cache.base import BaseCache
from openviper.cache.db_backend import DatabaseCache
from openviper.cache.memory import InMemoryCache
from openviper.cache.redis import RedisCache, redis_lib
from openviper.cache.validation import validate_cache_key
from openviper.conf import settings
from openviper.utils.importlib import import_string

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap, ConfigValue

cache_instances: dict[str, BaseCache] = {}
cache_lock: threading.Lock = threading.Lock()


def get_cache(alias: str = "default") -> BaseCache:
    """Return the cache backend for the given alias, creating it if necessary.

    Instances are stored in ``cache_instances`` and reused on subsequent calls.
    Thread-safe via ``cache_lock``.  Raises ``ValueError`` for unknown
    non-default aliases.
    """
    if alias in cache_instances:
        return cache_instances[alias]
    with cache_lock:
        if alias in cache_instances:
            return cache_instances[alias]
        caches_config: ConfigMap = cast("ConfigMap", settings.CACHES)
        if alias not in caches_config:
            if alias == "default":
                instance: BaseCache = InMemoryCache()
                cache_instances[alias] = instance
                return instance
            msg = f"Cache alias {alias!r} not found in settings.CACHES"
            raise ValueError(msg)
        config = cast("dict[str, ConfigValue]", caches_config[alias])
        backend_path: str = cast("str", config["BACKEND"])
        options: dict[str, Any] = cast("dict[str, Any]", config.get("OPTIONS", {}))
        if backend_path == "openviper.cache.InMemoryCache":
            backend_cls: type[BaseCache] = InMemoryCache
        elif backend_path == "openviper.cache.RedisCache":
            backend_cls = RedisCache
        elif backend_path == "openviper.cache.DatabaseCache":
            backend_cls = DatabaseCache
        else:
            backend_cls = cast("type[BaseCache]", import_string(backend_path))
        instance = backend_cls(**options)
        cache_instances[alias] = instance
        return instance


__all__ = [
    "BaseCache",
    "DatabaseCache",
    "InMemoryCache",
    "RedisCache",
    "get_cache",
    "redis_lib",
    "validate_cache_key",
]
