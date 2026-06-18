"""Unit tests for openviper.cache backends and get_cache factory."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import openviper.cache as cache_module
from openviper.cache import (
    BaseCache,
    DatabaseCache,
    DragonflyCache,
    FileCache,
    InMemoryCache,
    MemcachedCache,
    get_cache,
    validate_cache_key,
)
from openviper.cache.dragonfly import DragonflyCache as DragonflyCacheDirect
from openviper.cache.file import FileCache as FileCacheDirect
from openviper.cache.memcached import MemcachedCache as MemcachedCacheDirect
from openviper.cache.redis import RedisCache
from openviper.utils import timezone


@pytest.fixture(autouse=True)
def reset_cache_registry():
    """Isolate the global cache_instances registry for each test."""
    original = dict(cache_module.cache_instances)
    yield
    cache_module.cache_instances.clear()
    cache_module.cache_instances.update(original)


class TestBaseCache:
    """Tests for the BaseCache abstract base class."""

    def test_cannot_instantiate_directly(self):
        """BaseCache cannot be instantiated because it has abstract methods."""
        pytest.raises(TypeError, BaseCache)

    def test_concrete_subclass_must_implement_all_methods(self):
        """A subclass that omits any abstract method cannot be instantiated."""

        class Incomplete(BaseCache):
            async def get(self, key):
                return None

            # missing set, delete, clear

        pytest.raises(TypeError, Incomplete)


class TestInMemoryCache:
    """Tests for InMemoryCache."""

    async def test_get_missing_key_returns_none(self):
        """Getting a key that was never set returns None."""
        cache = InMemoryCache()
        assert await cache.get("missing") is None

    async def test_set_and_get(self):
        """A value set in the cache can be retrieved."""
        cache = InMemoryCache()
        await cache.set("key", "value")
        assert await cache.get("key") == "value"

    async def test_set_overwrites_existing_value(self):
        """Setting the same key twice stores the second value."""
        cache = InMemoryCache()
        await cache.set("k", "first")
        await cache.set("k", "second")
        assert await cache.get("k") == "second"

    async def test_delete_removes_key(self):
        """Deleting a key means it is no longer accessible."""
        cache = InMemoryCache()
        await cache.set("k", 42)
        await cache.delete("k")
        assert await cache.get("k") is None

    async def test_delete_nonexistent_key_is_safe(self):
        """Deleting a key that does not exist raises no exception."""
        cache = InMemoryCache()
        await cache.delete("ghost")

    async def test_clear_removes_all_keys(self):
        """clear() empties the cache."""
        cache = InMemoryCache()
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    async def test_ttl_expiry_returns_none_after_expiry(self):
        """A value with a TTL returns None after the TTL has elapsed."""
        cache = InMemoryCache()
        await cache.set("k", "v", ttl=1)
        # Manually push the expiry into the past
        val, _expiry = cache._data["k"]
        cache._data["k"] = (val, time.time() - 1)
        assert await cache.get("k") is None

    async def test_ttl_expiry_deletes_key_on_access(self):
        """After a TTL miss the key is removed from internal storage."""
        cache = InMemoryCache()
        await cache.set("k", "v", ttl=1)
        cache._data["k"] = (cache._data["k"][0], time.time() - 1)
        await cache.get("k")
        assert "k" not in cache._data

    async def test_no_ttl_never_expires(self):
        """A value stored without a TTL is always returned."""
        cache = InMemoryCache()
        await cache.set("persistent", "forever")
        assert await cache.get("persistent") == "forever"

    async def test_ttl_zero_expires_immediately(self):
        """A value with ttl=0 is immediately expired on next access."""
        cache = InMemoryCache()
        await cache.set("k", "v", ttl=0)
        # ttl=0 means expiry = time.time() + 0; it is already <= time.time()
        assert await cache.get("k") is None

    async def test_stores_complex_value(self):
        """Complex Python objects (dicts, lists) can be stored and retrieved."""
        cache = InMemoryCache()
        data = {"nested": [1, 2, {"deep": True}]}
        await cache.set("complex", data)
        assert await cache.get("complex") == data

    async def test_stores_none_value(self):
        """None can be stored as a value (distinct from missing key)."""
        cache = InMemoryCache()
        await cache.set("null_key", None)
        # After storing None, get should return None - indistinguishable from
        # missing, but the set should not raise.
        result = await cache.get("null_key")
        assert result is None  # None stored, None returned


class TestRedisCacheImportGuard:
    """Tests for RedisCache when the redis package is absent."""

    def test_raises_import_error_when_redis_not_installed(self):
        """Instantiating RedisCache without the redis package raises ImportError."""
        with patch("openviper.cache.redis.redis_lib", None):
            with pytest.raises(ImportError, match="redis"):
                cache_module.RedisCache()

    def test_raises_import_error_when_redis_not_installed_via_module(self):
        """Instantiating RedisCache via redis module without redis package raises ImportError."""
        with patch("openviper.cache.redis.redis_lib", None):
            with pytest.raises(ImportError, match="redis"):
                RedisCache()


class TestGetCache:
    """Tests for the get_cache() factory function."""

    def test_default_alias_returns_in_memory_cache(self):
        """With no CACHES setting, get_cache('default') returns InMemoryCache."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {}
            instance = get_cache("default")
        assert isinstance(instance, InMemoryCache)

    def test_default_alias_is_cached(self):
        """A second call for the same alias returns the same instance."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {}
            first = get_cache("default")
            second = get_cache("default")
        assert first is second

    def test_unknown_non_default_alias_raises(self):
        """Requesting an alias that is not in CACHES and is not 'default' raises ValueError."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {}
            with pytest.raises(ValueError, match="not found in settings.CACHES"):
                get_cache("unknown_alias")

    def test_explicit_in_memory_backend_in_settings(self):
        """An explicit InMemoryCache backend in CACHES is instantiated correctly."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "myalias": {"BACKEND": "openviper.cache.InMemoryCache", "OPTIONS": {}}
            }
            instance = get_cache("myalias")
        assert isinstance(instance, InMemoryCache)

    def test_database_backend_in_settings(self):
        """A DatabaseCache backend in CACHES is instantiated correctly."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "db": {"BACKEND": "openviper.cache.DatabaseCache", "OPTIONS": {}}
            }
            instance = get_cache("db")
        assert isinstance(instance, DatabaseCache)

    def test_custom_backend_via_import_string(self):
        """A custom backend path uses import_string to resolve the class."""

        class CustomCache(BaseCache):
            async def get(self, key):
                return None

            async def set(self, key, value, ttl=None):
                pass

            async def delete(self, key):
                pass

            async def clear(self):
                pass

        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "custom": {
                    "BACKEND": "mypackage.CustomCache",
                    "OPTIONS": {},
                }
            }
            with patch("openviper.cache.import_string", return_value=CustomCache):
                instance = get_cache("custom")

        assert isinstance(instance, CustomCache)


class TestDatabaseCacheGetModel:
    """Tests for the internal get_model() helper in DatabaseCache."""

    def test_returns_cache_entry_class(self):
        """get_model() returns the CacheEntry model class."""
        cache = DatabaseCache()
        model = cache.get_model()
        # CacheEntry may be None if import failed, but in a test env it should resolve
        assert model is not None

    def test_caches_model_lookup(self):
        """get_model() stores the result on _model_cache for subsequent calls."""
        cache = DatabaseCache()
        first = cache.get_model()
        second = cache.get_model()
        assert first is second
        assert cache._model_cache is first


class TestDatabaseCacheOperations:
    """Tests for DatabaseCache.get/set/delete/clear using mocked ORM."""

    def _patched_cache(self):
        """Return a DatabaseCache with CacheEntry mocked out."""
        fake_entry_cls = MagicMock()
        cache = DatabaseCache()
        cache._model_cache = fake_entry_cls
        return cache, fake_entry_cls

    async def test_get_missing_key_returns_none(self):
        """get() returns None when no entry exists for the key."""
        cache, fake_cls = self._patched_cache()
        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=None)
        fake_cls.objects.filter.return_value = fake_qs
        result = await cache.get("missing")
        assert result is None

    async def test_delete_calls_queryset_delete(self):
        """delete() filters by key and calls delete on the queryset."""
        cache, fake_cls = self._patched_cache()
        fake_qs = MagicMock()
        fake_qs.delete = AsyncMock()
        fake_cls.objects.filter.return_value = fake_qs
        await cache.delete("some_key")
        fake_cls.objects.filter.assert_called_once_with(key="some_key")
        fake_qs.delete.assert_awaited_once()

    async def test_clear_deletes_all(self):
        """clear() calls delete() on all() queryset."""
        cache, fake_cls = self._patched_cache()
        fake_qs = MagicMock()
        fake_qs.delete = AsyncMock()
        fake_cls.objects.all.return_value = fake_qs
        await cache.clear()
        fake_cls.objects.all.assert_called_once()
        fake_qs.delete.assert_awaited_once()

    async def test_get_with_non_expired_entry(self):
        """get() returns value for non-expired entries."""
        cache, fake_cls = self._patched_cache()
        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '{"data": "test"}'
        fake_entry.expires_at = timezone.now() + timedelta(hours=1)

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"data": "test"}
            result = await cache.get("test_key")

        assert result == {"data": "test"}

    async def test_get_with_expired_entry_deletes_it(self):
        """get() deletes expired entries and returns None."""
        cache, fake_cls = self._patched_cache()
        fake_entry = MagicMock()
        fake_entry.key = "expired_key"
        fake_entry.value = "expired_data"
        fake_entry.expires_at = timezone.now() - timedelta(hours=1)

        fake_qs_filter = MagicMock()
        fake_qs_filter.first = AsyncMock(return_value=fake_entry)
        fake_qs_delete = MagicMock()
        fake_qs_delete.delete = AsyncMock()
        fake_cls.objects.filter.side_effect = [fake_qs_filter, fake_qs_delete]

        result = await cache.get("expired_key")

        assert result is None
        assert fake_cls.objects.filter.call_count == 2
        fake_qs_delete.delete.assert_awaited_once()

    async def test_get_with_naive_expiry_and_aware_now(self):
        """get() handles timezone conversion when expiry is naive and now is aware."""
        cache, fake_cls = self._patched_cache()
        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '"test_value"'
        fake_entry.expires_at = datetime.now() + timedelta(hours=1)  # naive

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.db_backend.timezone") as mock_tz:
            mock_tz.now.return_value = timezone.now()  # aware
            mock_tz.is_aware = timezone.is_aware
            mock_tz.is_naive = timezone.is_naive
            mock_tz.make_aware.return_value = fake_entry.expires_at.replace(tzinfo=timezone.utc)

            with patch("openviper.cache.base.orjson") as mock_orjson:
                mock_orjson.loads.return_value = "test_value"
                result = await cache.get("test_key")

        assert result == "test_value"

    async def test_get_with_aware_expiry_and_naive_now(self):
        """get() handles timezone conversion when expiry is aware and now is naive."""
        cache, fake_cls = self._patched_cache()
        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '"test_value"'
        fake_entry.expires_at = timezone.now() + timedelta(hours=1)  # aware

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.db_backend.timezone") as mock_tz:
            mock_tz.now.return_value = datetime.now()  # naive
            mock_tz.is_aware = timezone.is_aware
            mock_tz.is_naive = timezone.is_naive
            mock_tz.make_naive.return_value = fake_entry.expires_at.astimezone().replace(
                tzinfo=None
            )

            with patch("openviper.cache.base.orjson") as mock_orjson:
                mock_orjson.loads.return_value = "test_value"
                result = await cache.get("test_key")

        assert result == "test_value"

    async def test_get_fallback_when_orjson_fails(self):
        """get() returns the raw value when orjson.loads() raises a ValueError."""
        cache, fake_cls = self._patched_cache()

        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = "plain_text"
        fake_entry.expires_at = None

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = ValueError("Parse error")
            result = await cache.get("test_key")

        assert result == "plain_text"

    async def test_set_with_ttl_postgresql(self):
        """set() uses PostgreSQL upsert when dialect is postgresql."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        mock_table = MagicMock()
        mock_table.name = "openviper_cache_entries"

        with patch("openviper.cache.db_backend.get_table", return_value=mock_table):
            with patch(
                "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
            ) as mock_get_engine:
                with patch("openviper.cache.db_backend.get_begin") as mock_get_begin:
                    mock_get_engine.return_value = mock_engine
                    mock_begin = MagicMock()
                    mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_begin.__aexit__ = AsyncMock(return_value=None)
                    mock_get_begin.return_value.return_value = mock_begin

                    await cache.set("key", "value", ttl=60)

                    mock_conn.execute.assert_awaited_once()

    async def test_set_with_ttl_sqlite(self):
        """set() uses SQLite upsert when dialect is sqlite."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        mock_table = MagicMock()
        mock_table.name = "openviper_cache_entries"

        with patch("openviper.cache.db_backend.get_table", return_value=mock_table):
            with patch(
                "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
            ) as mock_get_engine:
                with patch("openviper.cache.db_backend.get_begin") as mock_get_begin:
                    mock_get_engine.return_value = mock_engine
                    mock_begin = MagicMock()
                    mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_begin.__aexit__ = AsyncMock(return_value=None)
                    mock_get_begin.return_value.return_value = mock_begin

                    await cache.set("key", "value", ttl=60)

                    mock_conn.execute.assert_awaited_once()

    async def test_set_fallback_dialect_update_existing(self):
        """set() with unsupported dialect updates existing entry."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "mysql"  # unsupported dialect

        fake_entry = MagicMock()
        fake_entry.value = "old_value"
        fake_entry.expires_at = None
        fake_entry.save = AsyncMock()

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch(
            "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
        ) as mock_get_engine:
            mock_get_engine.return_value = mock_engine
            await cache.set("key", "new_value", ttl=60)

        assert fake_entry.value == "new_value"
        fake_entry.save.assert_awaited_once()

    async def test_set_fallback_dialect_create_new(self):
        """set() with unsupported dialect creates new entry if it does not exist."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "mysql"

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=None)
        fake_cls.objects.filter.return_value = fake_qs
        fake_cls.objects.create = AsyncMock()

        with patch(
            "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
        ) as mock_get_engine:
            mock_get_engine.return_value = mock_engine
            await cache.set("key", "value", ttl=60)

        fake_cls.objects.create.assert_awaited_once()

    async def test_set_complex_value_serialization(self):
        """set() serializes complex values with orjson."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        complex_value = {"nested": [1, 2, {"deep": True}]}

        mock_table = MagicMock()
        mock_table.name = "openviper_cache_entries"

        with patch("openviper.cache.db_backend.get_table", return_value=mock_table):
            with patch(
                "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
            ) as mock_get_engine:
                with patch("openviper.cache.db_backend.get_begin") as mock_get_begin:
                    with patch("openviper.cache.db_backend.orjson") as mock_orjson:
                        mock_get_engine.return_value = mock_engine
                        mock_begin = MagicMock()
                        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
                        mock_begin.__aexit__ = AsyncMock(return_value=None)
                        mock_get_begin.return_value.return_value = mock_begin
                        mock_orjson.dumps.return_value = b'{"nested":[1,2,{"deep":true}]}'

                        await cache.set("key", complex_value)

                        mock_orjson.dumps.assert_called_once_with(complex_value)

    async def test_set_primitive_value_no_serialization(self):
        """set() stores primitive values as strings without JSON encoding."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        mock_table = MagicMock()
        mock_table.name = "openviper_cache_entries"

        with patch("openviper.cache.db_backend.get_table", return_value=mock_table):
            with patch(
                "openviper.cache.db_backend.get_engine", new_callable=AsyncMock
            ) as mock_get_engine:
                with patch("openviper.cache.db_backend.get_begin") as mock_get_begin:
                    mock_get_engine.return_value = mock_engine
                    mock_begin = MagicMock()
                    mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_begin.__aexit__ = AsyncMock(return_value=None)
                    mock_get_begin.return_value.return_value = mock_begin

                    await cache.set("key", "simple_string")

                    mock_conn.execute.assert_awaited_once()


class TestRedisCacheOperations:
    """Tests for RedisCache operations with mocked redis client."""

    def _patched_redis_cache(self):
        """Return a RedisCache with mocked Redis client."""
        mock_client = MagicMock()
        with patch("openviper.cache.redis.redis_lib") as mock_redis_lib:
            mock_redis_lib.Redis.return_value = mock_client
            cache = cache_module.RedisCache()
        return cache, mock_client

    async def test_get_missing_key_returns_none(self):
        """get() returns None when Redis returns None."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.get = AsyncMock(return_value=None)

        result = await cache.get("missing")

        assert result is None
        mock_client.get.assert_awaited_once_with("ov:cache:missing")

    async def test_get_deserializes_json_value(self):
        """get() deserializes JSON values using orjson."""
        cache, mock_client = self._patched_redis_cache()
        json_bytes = b'{"key": "value"}'
        mock_client.get = AsyncMock(return_value=json_bytes)

        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"key": "value"}
            result = await cache.get("test_key")

        assert result == {"key": "value"}
        mock_orjson.loads.assert_called_once_with(json_bytes)

    async def test_get_returns_raw_value_on_orjson_error(self):
        """get() returns raw value when orjson.loads() raises a ValueError."""
        cache, mock_client = self._patched_redis_cache()
        raw_bytes = b"plain_text"
        mock_client.get = AsyncMock(return_value=raw_bytes)

        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = ValueError("Parse error")
            result = await cache.get("test_key")

        assert result == raw_bytes

    async def test_set_primitive_value(self):
        """set() stores primitive values directly."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()

        await cache.set("key", "string_value", ttl=60)

        mock_client.set.assert_awaited_once_with("ov:cache:key", "string_value", ex=60)

    async def test_set_complex_value_serializes(self):
        """set() serializes complex values with orjson."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()
        complex_value = {"nested": [1, 2, 3]}

        with patch("openviper.cache.redis.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'{"nested":[1,2,3]}'
            await cache.set("key", complex_value, ttl=60)

        mock_orjson.dumps.assert_called_once_with(complex_value)
        mock_client.set.assert_awaited_once_with("ov:cache:key", b'{"nested":[1,2,3]}', ex=60)

    async def test_set_without_ttl(self):
        """set() stores value without expiration when ttl is None."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()

        await cache.set("key", "value", ttl=None)

        mock_client.set.assert_awaited_once_with("ov:cache:key", "value", ex=None)

    async def test_delete_calls_redis_delete(self):
        """delete() calls Redis delete method with prefixed key."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.delete = AsyncMock()

        await cache.delete("key")

        mock_client.delete.assert_awaited_once_with("ov:cache:key")

    async def test_clear_uses_scan_and_unlink(self):
        """clear() uses SCAN and UNLINK to delete only prefixed keys."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.scan = AsyncMock(return_value=(0, [b"ov:cache:key1", b"ov:cache:key2"]))
        mock_client.unlink = AsyncMock()

        await cache.clear()

        mock_client.scan.assert_awaited_once_with(0, match="ov:cache:*", count=200)
        mock_client.unlink.assert_awaited_once_with(b"ov:cache:key1", b"ov:cache:key2")


class TestGetCacheRedis:
    """Tests for get_cache() with Redis backend."""

    def test_redis_backend_instantiation(self):
        """A RedisCache backend in CACHES is instantiated with OPTIONS."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "redis": {
                    "BACKEND": "openviper.cache.RedisCache",
                    "OPTIONS": {"host": "localhost", "port": 6379, "db": 1},
                }
            }
            with patch("openviper.cache.redis.redis_lib") as mock_redis_lib:
                instance = get_cache("redis")

            assert isinstance(instance, cache_module.RedisCache)
            mock_redis_lib.Redis.assert_called_once_with(host="localhost", port=6379, db=1)


@pytest.fixture
def mock_redis_client():
    mock_client = MagicMock()
    mock_client.get = AsyncMock()
    mock_client.set = AsyncMock()
    mock_client.delete = AsyncMock()
    mock_client.exists = AsyncMock()
    mock_client.scan = AsyncMock(return_value=(0, []))
    mock_client.unlink = AsyncMock()
    return mock_client


@pytest.mark.asyncio
async def test_redis_cache_get_set(mock_redis_client):
    with patch("openviper.cache.redis.redis_lib") as mock_redis_lib:
        mock_redis_lib.Redis.return_value = mock_redis_client
        cache = RedisCache()

        # Test set (complex value serialized with orjson)
        with patch("openviper.cache.redis.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'{"data": 123}'
            await cache.set("my_key", {"data": 123}, ttl=60)
        mock_redis_client.set.assert_called_once_with("ov:cache:my_key", b'{"data": 123}', ex=60)

        # Test get (JSON)
        mock_redis_client.get.return_value = b'{"data": 123}'
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"data": 123}
            val = await cache.get("my_key")
        assert val == {"data": 123}

        # Test get (Raw value on orjson error)
        mock_redis_client.get.return_value = b"raw string"
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = ValueError("parse error")
            val = await cache.get("my_key")
        assert val == b"raw string"

        # Test get (None)
        mock_redis_client.get.return_value = None
        val = await cache.get("missing", default="def")
        assert val == "def"


@pytest.mark.asyncio
async def test_redis_cache_ops(mock_redis_client):
    with patch("openviper.cache.redis.redis_lib") as mock_redis_lib:
        mock_redis_lib.Redis.return_value = mock_redis_client
        cache = RedisCache()

        # Delete
        await cache.delete("key")
        mock_redis_client.delete.assert_called_once_with("ov:cache:key")

        # Has key
        mock_redis_client.exists.return_value = 1
        assert await cache.has_key("key") is True

        # Clear uses SCAN + UNLINK
        mock_redis_client.scan.return_value = (0, [b"ov:cache:k1", b"ov:cache:k2"])
        await cache.clear()
        mock_redis_client.scan.assert_awaited_once_with(0, match="ov:cache:*", count=200)
        mock_redis_client.unlink.assert_called_once_with(b"ov:cache:k1", b"ov:cache:k2")


@pytest.mark.asyncio
async def test_redis_cache_import_error():
    with patch("openviper.cache.redis.redis_lib", None):
        with pytest.raises(ImportError, match="The 'redis' package is required"):
            RedisCache()


class TestValidateCacheKey:
    """Tests for the validate_cache_key function."""

    def test_valid_key(self):
        """Simple alphanumeric keys must pass validation."""
        assert validate_cache_key("user_1_data") == "user_1_data"

    def test_valid_key_with_dots_and_dashes(self):
        """Keys with dots, dashes, and underscores must pass validation."""
        assert validate_cache_key("cache.key-v1") == "cache.key-v1"

    def test_empty_key_raises(self):
        """Empty keys must be rejected."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_cache_key("")

    def test_whitespace_key_raises(self):
        """Keys containing whitespace must be rejected."""
        with pytest.raises(ValueError, match="invalid characters"):
            validate_cache_key("key with spaces")

    def test_bare_colon_key_raises(self):
        """Keys containing colons are allowed (standard Redis namespacing convention)."""
        # Colons are the standard Redis namespace delimiter and should be allowed.
        result = validate_cache_key("key:with:colons")
        assert result == "key:with:colons"

    def test_overlong_key_raises(self):
        """Keys exceeding the maximum length must be rejected."""
        with pytest.raises(ValueError, match="maximum length"):
            validate_cache_key("a" * 251)

    def test_max_length_key_passes(self):
        """Keys at exactly the maximum length must pass."""
        assert validate_cache_key("a" * 250) == "a" * 250

    @pytest.mark.asyncio
    async def test_in_memory_cache_rejects_empty_key(self):
        """InMemoryCache must reject empty keys via validate_cache_key."""
        cache = InMemoryCache()
        with pytest.raises(ValueError, match="not be empty"):
            await cache.get("")

    @pytest.mark.asyncio
    async def test_in_memory_cache_rejects_whitespace_key(self):
        """InMemoryCache must reject whitespace keys via validate_cache_key."""
        cache = InMemoryCache()
        with pytest.raises(ValueError, match="invalid characters"):
            await cache.set("bad key", "v")


class TestRedisCacheKeyPrefix:
    """Tests for RedisCache key prefix isolation."""

    def test_default_key_prefix(self):
        """RedisCache must use the ov:cache: prefix by default."""
        with patch("openviper.cache.redis.redis_lib"):
            cache = RedisCache()
            assert cache._prefix == "ov:cache:"

    def test_custom_key_prefix(self):
        """ "RedisCache must accept a custom key prefix."""

        with patch("openviper.cache.redis.redis_lib"):
            cache = RedisCache(key_prefix="myapp:")
            assert cache._prefix == "myapp:"

    def test_prefixed_key_format(self):
        """prefixed() must prepend the prefix to the key."""

        with patch("openviper.cache.redis.redis_lib"):
            cache = RedisCache()
            assert cache.prefixed("test") == "ov:cache:test"

    @pytest.mark.asyncio
    async def test_clear_uses_scan_not_flushdb(self):
        """clear() must use SCAN + UNLINK, never FLUSHDB."""
        with patch("openviper.cache.redis.redis_lib") as mock_lib:
            mock_client = MagicMock()
            mock_client.scan = AsyncMock(return_value=(0, []))
            mock_client.unlink = AsyncMock()
            mock_lib.Redis.return_value = mock_client
            cache = RedisCache()

            await cache.clear()

            mock_client.scan.assert_awaited_once()
            mock_client.unlink.assert_not_awaited()
            mock_client.flushdb.assert_not_called()


class TestMemcachedCacheImportGuard:
    """Tests for MemcachedCache when the aiomcache package is absent."""

    def test_raises_import_error_when_aiomcache_not_installed(self):
        """Instantiating MemcachedCache without aiomcache raises ImportError."""
        with patch("openviper.cache.memcached.mcache_lib", None):
            with pytest.raises(ImportError, match="aiomcache"):
                MemcachedCache()


class TestMemcachedCacheOperations:
    """Tests for MemcachedCache operations with mocked aiomcache client."""

    def _patched_memcached_cache(self):
        """Return a MemcachedCache with mocked aiomcache client."""
        mock_client = MagicMock()
        with patch("openviper.cache.memcached.mcache_lib") as mock_mcache_lib:
            mock_mcache_lib.Client.return_value = mock_client
            cache = MemcachedCache()
        return cache, mock_client

    async def test_get_missing_key_returns_none(self):
        """get() returns None when Memcached returns None."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.get = AsyncMock(return_value=None)
        result = await cache.get("missing")
        assert result is None

    async def test_get_deserializes_json_value(self):
        """get() deserializes JSON values using orjson."""
        cache, mock_client = self._patched_memcached_cache()
        json_bytes = b'{"key": "value"}'
        mock_client.get = AsyncMock(return_value=json_bytes)
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"key": "value"}
            result = await cache.get("test_key")
        assert result == {"key": "value"}

    async def test_get_returns_raw_value_on_orjson_error(self):
        """get() returns raw value when orjson.loads() raises."""
        cache, mock_client = self._patched_memcached_cache()
        raw_bytes = b"plain_text"
        mock_client.get = AsyncMock(return_value=raw_bytes)
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = ValueError("Parse error")
            result = await cache.get("test_key")
        assert result == raw_bytes

    async def test_set_complex_value_serializes(self):
        """set() serializes complex values with orjson."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.set = AsyncMock()
        complex_value = {"nested": [1, 2, 3]}
        with patch("openviper.cache.memcached.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'{"nested":[1,2,3]}'
            await cache.set("key", complex_value, ttl=60)
        mock_client.set.assert_awaited_once_with(b"ov:cache:key", b'{"nested":[1,2,3]}', exptime=60)

    async def test_set_without_ttl(self):
        """set() stores value with exptime=0 when ttl is None."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.set = AsyncMock()
        with patch("openviper.cache.memcached.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'"value"'
            await cache.set("key", "value", ttl=None)
        mock_client.set.assert_awaited_once_with(b"ov:cache:key", b'"value"', exptime=0)

    async def test_delete_calls_memcached_delete(self):
        """delete() calls Memcached delete method with prefixed key."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.delete = AsyncMock()
        await cache.delete("key")
        mock_client.delete.assert_awaited_once_with(b"ov:cache:key")

    async def test_clear_calls_flush_all(self):
        """clear() calls flush_all on the Memcached client."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.flush_all = AsyncMock()
        await cache.clear()
        mock_client.flush_all.assert_awaited_once()

    async def test_has_key_returns_true(self):
        """has_key() returns True when key exists."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.get = AsyncMock(return_value=b"some_value")
        assert await cache.has_key("key") is True

    async def test_has_key_returns_false(self):
        """has_key() returns False when key does not exist."""
        cache, mock_client = self._patched_memcached_cache()
        mock_client.get = AsyncMock(return_value=None)
        assert await cache.has_key("key") is False

    def test_default_key_prefix(self):
        """MemcachedCache must use the ov:cache: prefix by default."""
        with patch("openviper.cache.memcached.mcache_lib"):
            cache = MemcachedCache()
            assert cache._prefix == "ov:cache:"

    def test_custom_key_prefix(self):
        """MemcachedCache must accept a custom key prefix."""
        with patch("openviper.cache.memcached.mcache_lib"):
            cache = MemcachedCache(key_prefix="myapp:")
            assert cache._prefix == "myapp:"

    def test_custom_host_and_port(self):
        """MemcachedCache must accept custom host and port."""
        with patch("openviper.cache.memcached.mcache_lib") as mock_lib:
            MemcachedCache(host="mc.example.com", port=11212)
            mock_lib.Client.assert_called_once_with(host="mc.example.com", port=11212)


class TestFileCacheOperations:
    """Tests for FileCache operations using a temporary directory."""

    async def test_get_missing_key_returns_none(self, tmp_path):
        """get() returns None when no file exists for the key."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        result = await cache.get("missing")
        assert result is None

    async def test_set_and_get(self, tmp_path):
        """A value set in the file cache can be retrieved."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    async def test_set_complex_value(self, tmp_path):
        """Complex Python objects can be stored and retrieved."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        data = {"nested": [1, 2, {"deep": True}]}
        await cache.set("complex", data)
        result = await cache.get("complex")
        assert result == data

    async def test_set_overwrites_existing_value(self, tmp_path):
        """Setting the same key twice stores the second value."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("k", "first")
        await cache.set("k", "second")
        assert await cache.get("k") == "second"

    async def test_delete_removes_key(self, tmp_path):
        """Deleting a key means it is no longer accessible."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("k", 42)
        await cache.delete("k")
        assert await cache.get("k") is None

    async def test_delete_nonexistent_key_is_safe(self, tmp_path):
        """Deleting a key that does not exist raises no exception."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.delete("ghost")

    async def test_clear_removes_all_keys(self, tmp_path):
        """clear() empties the cache directory."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    async def test_ttl_expiry_returns_none_after_expiry(self, tmp_path):
        """A value with a TTL returns None after the TTL has elapsed."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("k", "v", ttl=1)
        # Manually push the expiry into the past by rewriting the file
        import orjson as _orjson

        filepath = cache.filepath("k")
        entry = _orjson.loads(filepath.read_bytes())
        entry["expiry"] = time.time() - 1
        filepath.write_bytes(_orjson.dumps(entry))
        assert await cache.get("k") is None

    async def test_no_ttl_never_expires(self, tmp_path):
        """A value stored without a TTL is always returned."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("persistent", "forever")
        assert await cache.get("persistent") == "forever"

    async def test_has_key_returns_true(self, tmp_path):
        """has_key() returns True when key exists and is not expired."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("key", "value")
        assert await cache.has_key("key") is True

    async def test_has_key_returns_false_for_missing(self, tmp_path):
        """has_key() returns False when key does not exist."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        assert await cache.has_key("missing") is False

    async def test_has_key_returns_false_for_expired(self, tmp_path):
        """has_key() returns False and deletes expired entries."""
        cache = FileCache(cache_dir=str(tmp_path / "cache"))
        await cache.set("k", "v", ttl=1)
        import orjson as _orjson

        filepath = cache.filepath("k")
        entry = _orjson.loads(filepath.read_bytes())
        entry["expiry"] = time.time() - 1
        filepath.write_bytes(_orjson.dumps(entry))
        assert await cache.has_key("k") is False

    def test_default_key_prefix(self):
        """FileCache must use the ov:cache: prefix by default."""
        cache = FileCache(cache_dir="/tmp/test_cache")
        assert cache._prefix == "ov:cache:"

    def test_custom_key_prefix(self):
        """FileCache must accept a custom key prefix."""
        cache = FileCache(cache_dir="/tmp/test_cache", key_prefix="myapp:")
        assert cache._prefix == "myapp:"

    def test_safe_filename_hex_encoding(self):
        """_safe_filename must hex-encode keys to avoid filesystem issues."""
        from openviper.cache.file import safe_filename

        assert safe_filename("simple_key") == "73696d706c655f6b6579"
        assert safe_filename("key/with:chars") == "6b65792f776974683a6368617273"


class TestDragonflyCacheImportGuard:
    """Tests for DragonflyCache when the redis package is absent."""

    def test_raises_import_error_when_redis_not_installed(self):
        """Instantiating DragonflyCache without the redis package raises ImportError."""
        with patch("openviper.cache.redis.redis_lib", None):
            with pytest.raises(ImportError, match="redis"):
                DragonflyCache()


class TestDragonflyCacheOperations:
    """Tests for DragonflyCache operations with mocked redis client."""

    def _patched_dragonfly_cache(self):
        """Return a DragonflyCache with mocked Redis client."""
        mock_client = MagicMock()
        with patch("openviper.cache.redis.redis_lib") as mock_redis_lib:
            mock_redis_lib.Redis.return_value = mock_client
            cache = DragonflyCache()
        return cache, mock_client

    async def test_get_missing_key_returns_none(self):
        """get() returns None when Dragonfly returns None."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.get = AsyncMock(return_value=None)
        result = await cache.get("missing")
        assert result is None

    async def test_get_deserializes_json_value(self):
        """get() deserializes JSON values using orjson."""
        cache, mock_client = self._patched_dragonfly_cache()
        json_bytes = b'{"key": "value"}'
        mock_client.get = AsyncMock(return_value=json_bytes)
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"key": "value"}
            result = await cache.get("test_key")
        assert result == {"key": "value"}

    async def test_get_returns_raw_value_on_orjson_error(self):
        """get() returns raw value when orjson.loads() raises."""
        cache, mock_client = self._patched_dragonfly_cache()
        raw_bytes = b"plain_text"
        mock_client.get = AsyncMock(return_value=raw_bytes)
        with patch("openviper.cache.base.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = ValueError("Parse error")
            result = await cache.get("test_key")
        assert result == raw_bytes

    async def test_set_primitive_value(self):
        """set() stores primitive values directly."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.set = AsyncMock()
        await cache.set("key", "string_value", ttl=60)
        mock_client.set.assert_awaited_once_with("ov:df:key", "string_value", ex=60)

    async def test_set_complex_value_serializes(self):
        """set() serializes complex values with orjson."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.set = AsyncMock()
        complex_value = {"nested": [1, 2, 3]}
        with patch("openviper.cache.redis.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'{"nested":[1,2,3]}'
            await cache.set("key", complex_value, ttl=60)
        mock_orjson.dumps.assert_called_once_with(complex_value)
        mock_client.set.assert_awaited_once_with("ov:df:key", b'{"nested":[1,2,3]}', ex=60)

    async def test_set_without_ttl(self):
        """set() stores value without expiration when ttl is None."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.set = AsyncMock()
        await cache.set("key", "value", ttl=None)
        mock_client.set.assert_awaited_once_with("ov:df:key", "value", ex=None)

    async def test_delete_calls_redis_delete(self):
        """delete() calls Redis delete method with prefixed key."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.delete = AsyncMock()
        await cache.delete("key")
        mock_client.delete.assert_awaited_once_with("ov:df:key")

    async def test_clear_uses_scan_and_unlink(self):
        """clear() uses SCAN and UNLINK to delete only prefixed keys."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.scan = AsyncMock(return_value=(0, [b"ov:df:key1", b"ov:df:key2"]))
        mock_client.unlink = AsyncMock()
        await cache.clear()
        mock_client.scan.assert_awaited_once_with(0, match="ov:df:*", count=200)
        mock_client.unlink.assert_awaited_once_with(b"ov:df:key1", b"ov:df:key2")

    async def test_has_key_returns_true(self):
        """has_key() returns True when key exists."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.exists = AsyncMock(return_value=1)
        assert await cache.has_key("key") is True

    async def test_has_key_returns_false(self):
        """has_key() returns False when key does not exist."""
        cache, mock_client = self._patched_dragonfly_cache()
        mock_client.exists = AsyncMock(return_value=0)
        assert await cache.has_key("key") is False

    def test_default_key_prefix(self):
        """DragonflyCache must use the ov:df: prefix by default."""
        with patch("openviper.cache.redis.redis_lib"):
            cache = DragonflyCache()
            assert cache._prefix == "ov:df:"

    def test_custom_key_prefix(self):
        """DragonflyCache must accept a custom key prefix."""
        with patch("openviper.cache.redis.redis_lib"):
            cache = DragonflyCache(key_prefix="myapp:")
            assert cache._prefix == "myapp:"

    def test_custom_host_port_db(self):
        """DragonflyCache must accept custom host, port, and db parameters."""
        with patch("openviper.cache.redis.redis_lib") as mock_lib:
            DragonflyCache(host="df.example.com", port=6380, db=2)
            mock_lib.Redis.assert_called_once_with(host="df.example.com", port=6380, db=2)


class TestGetCacheNewBackends:
    """Tests for get_cache() with the new backend types."""

    def test_memcached_backend_in_settings(self):
        """A MemcachedCache backend in CACHES is instantiated correctly."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "mc": {"BACKEND": "openviper.cache.MemcachedCache", "OPTIONS": {}}
            }
            with patch("openviper.cache.memcached.mcache_lib"):
                instance = get_cache("mc")
        assert isinstance(instance, MemcachedCache)

    def test_file_backend_in_settings(self):
        """A FileCache backend in CACHES is instantiated correctly."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {"file": {"BACKEND": "openviper.cache.FileCache", "OPTIONS": {}}}
            instance = get_cache("file")
        assert isinstance(instance, FileCache)

    def test_dragonfly_backend_in_settings(self):
        """A DragonflyCache backend in CACHES is instantiated correctly."""
        with patch("openviper.cache.settings") as mock_settings:
            mock_settings.CACHES = {
                "df": {"BACKEND": "openviper.cache.DragonflyCache", "OPTIONS": {}}
            }
            with patch("openviper.cache.redis.redis_lib"):
                instance = get_cache("df")
        assert isinstance(instance, DragonflyCache)
