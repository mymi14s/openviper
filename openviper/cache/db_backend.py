"""Database-backed cache implementation using the OpenViper ORM with orjson serialization."""

from __future__ import annotations

import datetime
import typing as t
from typing import TYPE_CHECKING

import orjson
import sqlalchemy as sa

from openviper.cache.base import BaseCache, deserialize_cache_value
from openviper.cache.db import CacheEntry
from openviper.cache.validation import validate_cache_key
from openviper.db.connection import get_engine
from openviper.db.executor import get_table
from openviper.db.utils import validate_identifier
from openviper.utils import timezone

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def validate_table_name(name: str) -> str:
    """Validate that *name* is a safe SQL table identifier.

    Non-string values (e.g. from mocked table objects in tests) are
    coerced to ``str`` before validation.
    """
    return validate_identifier(str(name), "table name")


def get_begin(engine: sa.Engine | AsyncEngine) -> t.Callable[[], t.Any]:
    """Return the engine.begin callable for the given engine."""
    return engine.begin


def is_entry_expired(expires_at: datetime.datetime | None) -> bool:
    """Return ``True`` when *expires_at* is in the past relative to now.

    Handles timezone-aware/naive mismatches by converting to a common
    timezone before comparison.
    """
    if expires_at is None:
        return False
    now = timezone.now()
    exp = expires_at
    if timezone.is_naive(exp) and timezone.is_aware(now):
        exp = timezone.make_aware(exp)
    elif timezone.is_aware(exp) and timezone.is_naive(now):
        exp = timezone.make_naive(exp)
    return exp <= now


class DatabaseCache(BaseCache):
    """Database-backed cache using the OpenViper ORM with orjson serialization."""

    def __init__(self, **kwargs: t.Any) -> None:
        """Initialise the database cache with a lazily-resolved model.

        Accepts and ignores extra keyword arguments so that OPTIONS
        like ``ttl`` can be present in the CACHES config without
        causing ``TypeError``.
        """
        self._model_cache: type | None = None

    def get_model(self) -> type:
        """Return the CacheEntry model class, caching the result on this instance."""
        if self._model_cache is None:
            self._model_cache = CacheEntry
        return self._model_cache

    async def get(self, key: str, default: t.Any = None) -> t.Any:  # noqa: ANN401
        """Fetch a value from the cache, returning *default* on miss."""
        validate_cache_key(key)
        cls = self.get_model()
        entry = await cls.objects.filter(key=key).first()
        if entry is None:
            return default
        if is_entry_expired(entry.expires_at):
            await cls.objects.filter(key=key).delete()
            return default
        result = deserialize_cache_value(entry.value, key)
        return result

    async def set(self, key: str, value: t.Any, ttl: int | None = None) -> None:  # noqa: ANN401
        """Store a value in the cache with an optional TTL."""
        validate_cache_key(key)
        cls = self.get_model()
        engine = await get_engine()
        if isinstance(value, (dict, list)):
            serialized: str = orjson.dumps(value).decode()
        elif isinstance(value, str):
            serialized = value
        else:
            serialized = str(value)
        expires_at = None
        if ttl is not None:
            expires_at = timezone.now() + datetime.timedelta(seconds=ttl)
        dialect = engine.dialect.name
        if dialect in ("postgresql", "sqlite"):
            table = get_table(cls)
            table_name = validate_table_name(getattr(table, "name", "openviper_cache_entries"))
            async with get_begin(engine)() as conn:
                if dialect == "postgresql":
                    stmt = sa.text(
                        f"INSERT INTO {table_name} (key, value, expires_at)"  # noqa: S608
                        " VALUES (:key, :value, :expires_at)"
                        " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,"
                        " expires_at = EXCLUDED.expires_at",
                    )
                else:
                    stmt = sa.text(
                        f"INSERT OR REPLACE INTO {table_name} (key, value, expires_at)"  # noqa: S608
                        " VALUES (:key, :value, :expires_at)",
                    )
                await conn.execute(
                    stmt,
                    {"key": key, "value": serialized, "expires_at": expires_at},
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
        """Remove a value from the cache."""
        validate_cache_key(key)
        cls = self.get_model()
        await cls.objects.filter(key=key).delete()

    async def clear(self) -> None:
        """Remove all values from the cache."""
        cls = self.get_model()
        await cls.objects.all().delete()

    async def has_key(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        validate_cache_key(key)
        cls = self.get_model()
        entry = await cls.objects.filter(key=key).first()
        if entry is None:
            return False
        if is_entry_expired(entry.expires_at):
            await cls.objects.filter(key=key).delete()
            return False
        return True
