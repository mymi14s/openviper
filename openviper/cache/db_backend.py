"""Database-backed cache implementation using the OpenViper ORM with orjson serialization."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

import orjson
import sqlalchemy as sa

from openviper.cache.base import BaseCache
from openviper.cache.db import CacheEntry
from openviper.db.connection import get_engine

logger = logging.getLogger(__name__)

from openviper.db.executor import get_table  # noqa: E402
from openviper.utils import timezone  # noqa: E402

_SAFE_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table_name(name: Any) -> str:
    """Validate that *name* is a safe SQL identifier.

    Non-string values (e.g. from mocked table objects in tests) are
    coerced to ``str`` before validation.

    Raises:
        ValueError: If *name* contains characters outside the safe set
            for SQL identifiers.
    """
    name_str = str(name)
    if not _SAFE_TABLE_RE.match(name_str):
        raise ValueError(
            f"Invalid table name {name_str!r}: must match pattern [a-zA-Z_][a-zA-Z0-9_]*"
        )
    return name_str


def _get_begin(engine: Any) -> Any:
    """Return the engine.begin callable for the given engine."""
    return engine.begin


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
            logger.debug("Failed to deserialize cached value", exc_info=True)
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
            table_name = _validate_table_name(getattr(table, "name", "openviper_cache_entries"))
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
