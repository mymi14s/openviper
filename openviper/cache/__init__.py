"""Cache framework providing a unified async interface for multiple backends."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from openviper.cache.base import BaseCache
from openviper.cache.db_backend import DatabaseCache
from openviper.cache.dragonfly import DragonflyCache
from openviper.cache.file import FileCache
from openviper.cache.memcached import MemcachedCache
from openviper.cache.memory import InMemoryCache
from openviper.cache.redis import RedisCache, redis_lib
from openviper.cache.validation import validate_cache_key
from openviper.conf import settings
from openviper.utils.importlib import import_string

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap, ConfigValue

cache_instances: dict[str, BaseCache] = {}
cache_lock: threading.Lock = threading.Lock()

_BACKEND_MAP: dict[str, type[BaseCache]] = {
    "openviper.cache.InMemoryCache": InMemoryCache,
    "openviper.cache.RedisCache": RedisCache,
    "openviper.cache.DatabaseCache": DatabaseCache,
    "openviper.cache.MemcachedCache": MemcachedCache,
    "openviper.cache.FileCache": FileCache,
    "openviper.cache.DragonflyCache": DragonflyCache,
}


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
        backend_cls: type[BaseCache]
        if backend_path in _BACKEND_MAP:
            backend_cls = _BACKEND_MAP[backend_path]
        else:
            backend_cls = cast("type[BaseCache]", import_string(backend_path))
        instance = backend_cls(**options)
        cache_instances[alias] = instance
        return instance


def get_cache_url(alias: str = "default") -> str:
    """Return the connection URL for a cache alias from CACHES config.

    Reads the ``url`` key from the alias OPTIONS dict.  Falls back to
    ``CACHE_URL`` for backward compatibility with the legacy flat-settings
    format.  Returns an empty string when no URL is configured.
    """
    caches_config: ConfigMap = cast("ConfigMap", settings.CACHES)
    if isinstance(caches_config, Mapping):
        config = caches_config.get(alias)
        if isinstance(config, Mapping):
            options = config.get("OPTIONS")
            if isinstance(options, Mapping):
                url = options.get("url") or options.get("URL")
                if isinstance(url, str) and url:
                    return url
    # Legacy fallback
    cache_url = getattr(settings, "CACHE_URL", "")
    if isinstance(cache_url, str) and cache_url:
        return cache_url
    return ""


__all__ = [
    "BaseCache",
    "DatabaseCache",
    "DragonflyCache",
    "FileCache",
    "InMemoryCache",
    "MemcachedCache",
    "RedisCache",
    "get_cache",
    "get_cache_url",
    "redis_lib",
    "validate_cache_key",
]
