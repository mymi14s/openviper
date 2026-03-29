from __future__ import annotations

import datetime
from typing import Any

import orjson
import sqlalchemy as sa

from openviper.cache.base import BaseCache
from openviper.cache.db import CacheEntry
from openviper.cache.memory import InMemoryCache
from openviper.conf import settings
from openviper.db.connection import get_engine
from openviper.db.executor import get_table
from openviper.utils import timezone
from openviper.utils.importlib import import_string

try:
    import redis.asyncio as redis_lib
except ImportError:
    redis_lib = None  # type: ignore[assignment]

_cache_instances: dict[str, BaseCache] = {}


def _get_begin(engine: Any) -> Any:
    """Return the engine.begin callable for the given engine."""
    return engine.begin


class RedisCache(BaseCache):
    """Redis-backed cache using redis.asyncio with orjson serialization."""

    def __init__(self, **kwargs: Any) -> None:
        if redis_lib is None:
            raise ImportError(
                "The 'redis' package is required to use RedisCache. "
                "Install it with: pip install redis"
            )
        self._client = redis_lib.Redis(**kwargs)

    async def get(self, key: str, default: Any = None) -> Any:
        value = await self._client.get(key)
        if value is None:
            return default
        try:
            return orjson.loads(value)
        except Exception:
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if isinstance(value, (dict, list)):
            serialized: Any = orjson.dumps(value)
        else:
            serialized = value
        await self._client.set(key, serialized, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def clear(self) -> None:
        await self._client.flushdb()

    async def has_key(self, key: str) -> bool:
        return bool(await self._client.exists(key))


class DatabaseCache(BaseCache):
    """Database-backed cache using the OpenViper ORM with orjson serialization."""

    def __init__(self) -> None:
        self._model_cache: type | None = None

    def _get_model(self) -> type:
        """Return the CacheEntry model class, caching the result on this instance."""
        if self._model_cache is None:
            self._model_cache = CacheEntry
        return self._model_cache

    async def get(self, key: str, default: Any = None) -> Any:
        cls = self._get_model()
        entry = await cls.objects.filter(key=key).first()
        if entry is None:
            return default
        if entry.expires_at is not None:
            now = timezone.now()
            exp = entry.expires_at
            if timezone.is_naive(exp) and timezone.is_aware(now):
                exp = timezone.make_aware(exp)
            elif timezone.is_aware(exp) and timezone.is_naive(now):
                exp = timezone.make_naive(exp)
            if exp <= now:
                await cls.objects.filter(key=key).delete()
                return default
        try:
            return orjson.loads(entry.value)
        except Exception:
            return entry.value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        cls = self._get_model()
        engine = await get_engine()
        if isinstance(value, (dict, list)):
            serialized: str = orjson.dumps(value).decode()
        else:
            serialized = value if isinstance(value, str) else str(value)
        expires_at = None
        if ttl is not None:
            expires_at = timezone.now() + datetime.timedelta(seconds=ttl)
        dialect = engine.dialect.name
        if dialect in ("postgresql", "sqlite"):
            table = get_table(cls)
            table_name = getattr(table, "name", "openviper_cache_entries")
            async with _get_begin(engine)() as conn:
                if dialect == "postgresql":
                    stmt = sa.text(
                        f"INSERT INTO {table_name} (key, value, expires_at)"
                        " VALUES (:key, :value, :expires_at)"
                        " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,"
                        " expires_at = EXCLUDED.expires_at"
                    )
                else:
                    stmt = sa.text(
                        f"INSERT OR REPLACE INTO {table_name} (key, value, expires_at)"
                        " VALUES (:key, :value, :expires_at)"
                    )
                await conn.execute(
                    stmt, {"key": key, "value": serialized, "expires_at": expires_at}
                )
        else:
            entry = await cls.objects.filter(key=key).first()
            if entry is not None:
                entry.value = serialized
                entry.expires_at = expires_at
                await entry.save()
            else:
                await cls.objects.create(key=key, value=serialized, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        cls = self._get_model()
        await cls.objects.filter(key=key).delete()

    async def clear(self) -> None:
        cls = self._get_model()
        await cls.objects.all().delete()

    async def has_key(self, key: str) -> bool:
        cls = self._get_model()
        entry = await cls.objects.filter(key=key).first()
        if entry is None:
            return False
        if entry.expires_at is not None:
            now = timezone.now()
            exp = entry.expires_at
            if timezone.is_naive(exp) and timezone.is_aware(now):
                exp = timezone.make_aware(exp)
            elif timezone.is_aware(exp) and timezone.is_naive(now):
                exp = timezone.make_naive(exp)
            if exp <= now:
                await cls.objects.filter(key=key).delete()
                return False
        return True


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
