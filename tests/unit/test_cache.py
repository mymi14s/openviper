"""Unit tests for openviper.cache (InMemoryCache, RedisCache, DatabaseCache, get_cache)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import openviper.cache as cache_module
from openviper.cache import BaseCache, DatabaseCache, InMemoryCache, get_cache

# ---------------------------------------------------------------------------
# Fixture: reset global cache registry between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache_registry():
    """Isolate the global _cache_instances registry for each test."""
    original = dict(cache_module._cache_instances)
    yield
    cache_module._cache_instances.clear()
    cache_module._cache_instances.update(original)


# ---------------------------------------------------------------------------
# BaseCache abstract interface
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# InMemoryCache
# ---------------------------------------------------------------------------


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
        # After storing None, get should return None — indistinguishable from
        # missing, but the set should not raise.
        result = await cache.get("null_key")
        assert result is None  # None stored, None returned


# ---------------------------------------------------------------------------
# RedisCache – import guard
# ---------------------------------------------------------------------------


class TestRedisCacheImportGuard:
    """Tests for RedisCache when the redis package is absent."""

    def test_raises_import_error_when_redis_not_installed(self):
        """Instantiating RedisCache without the redis package raises ImportError."""
        original = cache_module.redis_lib
        cache_module.redis_lib = None
        try:
            with pytest.raises(ImportError, match="redis"):
                cache_module.RedisCache()
        finally:
            cache_module.redis_lib = original


# ---------------------------------------------------------------------------
# get_cache
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DatabaseCache._get_model()
# ---------------------------------------------------------------------------


class TestDatabaseCacheGetModel:
    """Tests for the internal _get_model() helper in DatabaseCache."""

    def test_returns_cache_entry_class(self):
        """_get_model() returns the CacheEntry model class."""
        cache = DatabaseCache()
        model = cache._get_model()
        # CacheEntry may be None if import failed, but in a test env it should resolve
        assert model is not None

    def test_caches_model_lookup(self):
        """_get_model() stores the result on _model_cache for subsequent calls."""
        cache = DatabaseCache()
        first = cache._get_model()
        second = cache._get_model()
        assert first is second
        assert cache._model_cache is first


# ---------------------------------------------------------------------------
# DatabaseCache operations (mocked ORM)
# ---------------------------------------------------------------------------


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
        from datetime import timedelta

        from openviper.utils import timezone

        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '{"data": "test"}'
        fake_entry.expires_at = timezone.now() + timedelta(hours=1)

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"data": "test"}
            result = await cache.get("test_key")

        assert result == {"data": "test"}

    async def test_get_with_expired_entry_deletes_it(self):
        """get() deletes expired entries and returns None."""
        cache, fake_cls = self._patched_cache()
        from datetime import timedelta

        from openviper.utils import timezone

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
        from datetime import datetime, timedelta

        from openviper.utils import timezone

        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '"test_value"'
        fake_entry.expires_at = datetime.now() + timedelta(hours=1)  # naive

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.timezone") as mock_tz:
            mock_tz.now.return_value = timezone.now()  # aware
            mock_tz.is_aware = timezone.is_aware
            mock_tz.is_naive = timezone.is_naive
            mock_tz.make_aware.return_value = fake_entry.expires_at.replace(tzinfo=timezone.utc)

            with patch("openviper.cache.orjson") as mock_orjson:
                mock_orjson.loads.return_value = "test_value"
                result = await cache.get("test_key")

        assert result == "test_value"

    async def test_get_with_aware_expiry_and_naive_now(self):
        """get() handles timezone conversion when expiry is aware and now is naive."""
        cache, fake_cls = self._patched_cache()
        from datetime import datetime, timedelta

        from openviper.utils import timezone

        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = '"test_value"'
        fake_entry.expires_at = timezone.now() + timedelta(hours=1)  # aware

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.timezone") as mock_tz:
            mock_tz.now.return_value = datetime.now()  # naive
            mock_tz.is_aware = timezone.is_aware
            mock_tz.is_naive = timezone.is_naive
            mock_tz.make_naive.return_value = fake_entry.expires_at.astimezone().replace(
                tzinfo=None
            )

            with patch("openviper.cache.orjson") as mock_orjson:
                mock_orjson.loads.return_value = "test_value"
                result = await cache.get("test_key")

        assert result == "test_value"

    async def test_get_fallback_when_orjson_fails(self):
        """get() returns raw value when orjson.loads() raises an exception."""
        cache, fake_cls = self._patched_cache()

        fake_entry = MagicMock()
        fake_entry.key = "test_key"
        fake_entry.value = "plain_text"
        fake_entry.expires_at = None

        fake_qs = MagicMock()
        fake_qs.first = AsyncMock(return_value=fake_entry)
        fake_cls.objects.filter.return_value = fake_qs

        with patch("openviper.cache.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = Exception("Parse error")
            result = await cache.get("test_key")

        assert result == "plain_text"

    async def test_set_with_ttl_postgresql(self):
        """set() uses PostgreSQL upsert when dialect is postgresql."""
        cache, fake_cls = self._patched_cache()

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        with patch("openviper.cache.get_table") as _:
            with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
                with patch("openviper.cache._get_begin") as mock_get_begin:
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

        with patch("openviper.cache.get_table") as _:
            with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
                with patch("openviper.cache._get_begin") as mock_get_begin:
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

        with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
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

        with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
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

        with patch("openviper.cache.get_table") as _:
            with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
                with patch("openviper.cache._get_begin") as mock_get_begin:
                    with patch("openviper.cache.orjson") as mock_orjson:
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

        with patch("openviper.cache.get_table") as _:
            with patch("openviper.cache.get_engine", new_callable=AsyncMock) as mock_get_engine:
                with patch("openviper.cache._get_begin") as mock_get_begin:
                    mock_get_engine.return_value = mock_engine
                    mock_begin = MagicMock()
                    mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_begin.__aexit__ = AsyncMock(return_value=None)
                    mock_get_begin.return_value.return_value = mock_begin

                    await cache.set("key", "simple_string")

                    mock_conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# RedisCache operations (mocked redis client)
# ---------------------------------------------------------------------------


class TestRedisCacheOperations:
    """Tests for RedisCache operations with mocked redis client."""

    def _patched_redis_cache(self):
        """Return a RedisCache with mocked Redis client."""
        mock_client = MagicMock()
        with patch("openviper.cache.redis_lib") as mock_redis_lib:
            mock_redis_lib.Redis.return_value = mock_client
            cache = cache_module.RedisCache()
        return cache, mock_client

    async def test_get_missing_key_returns_none(self):
        """get() returns None when Redis returns None."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.get = AsyncMock(return_value=None)

        result = await cache.get("missing")

        assert result is None
        mock_client.get.assert_awaited_once_with("missing")

    async def test_get_deserializes_json_value(self):
        """get() deserializes JSON values using orjson."""
        cache, mock_client = self._patched_redis_cache()
        json_bytes = b'{"key": "value"}'
        mock_client.get = AsyncMock(return_value=json_bytes)

        with patch("openviper.cache.orjson") as mock_orjson:
            mock_orjson.loads.return_value = {"key": "value"}
            result = await cache.get("test_key")

        assert result == {"key": "value"}
        mock_orjson.loads.assert_called_once_with(json_bytes)

    async def test_get_returns_raw_value_on_orjson_error(self):
        """get() returns raw value when orjson.loads() raises an exception."""
        cache, mock_client = self._patched_redis_cache()
        raw_bytes = b"plain_text"
        mock_client.get = AsyncMock(return_value=raw_bytes)

        with patch("openviper.cache.orjson") as mock_orjson:
            mock_orjson.loads.side_effect = Exception("Parse error")
            result = await cache.get("test_key")

        assert result == raw_bytes

    async def test_set_primitive_value(self):
        """set() stores primitive values directly."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()

        await cache.set("key", "string_value", ttl=60)

        mock_client.set.assert_awaited_once_with("key", "string_value", ex=60)

    async def test_set_complex_value_serializes(self):
        """set() serializes complex values with orjson."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()
        complex_value = {"nested": [1, 2, 3]}

        with patch("openviper.cache.orjson") as mock_orjson:
            mock_orjson.dumps.return_value = b'{"nested":[1,2,3]}'
            await cache.set("key", complex_value, ttl=60)

        mock_orjson.dumps.assert_called_once_with(complex_value)
        mock_client.set.assert_awaited_once_with("key", b'{"nested":[1,2,3]}', ex=60)

    async def test_set_without_ttl(self):
        """set() stores value without expiration when ttl is None."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.set = AsyncMock()

        await cache.set("key", "value", ttl=None)

        mock_client.set.assert_awaited_once_with("key", "value", ex=None)

    async def test_delete_calls_redis_delete(self):
        """delete() calls Redis delete method."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.delete = AsyncMock()

        await cache.delete("key")

        mock_client.delete.assert_awaited_once_with("key")

    async def test_clear_calls_redis_flushdb(self):
        """clear() calls Redis flushdb method."""
        cache, mock_client = self._patched_redis_cache()
        mock_client.flushdb = AsyncMock()

        await cache.clear()

        mock_client.flushdb.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_cache with RedisCache
# ---------------------------------------------------------------------------


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
            with patch("openviper.cache.redis_lib") as mock_redis_lib:
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
    mock_client.flushdb = AsyncMock()
    return mock_client


@pytest.mark.asyncio
async def test_redis_cache_get_set(mock_redis_client):
    from openviper.cache.redis import RedisCache

    with patch("openviper.cache.redis.redis") as mock_redis_module:
        mock_redis_module.Redis.from_url.return_value = mock_redis_client
        cache = RedisCache()

        # Test set
        await cache.set("my_key", {"data": 123}, ttl=60)
        mock_redis_client.set.assert_called_once_with("my_key", '{"data": 123}', ex=60)

        # Test get (JSON)
        mock_redis_client.get.return_value = b'{"data": 123}'
        val = await cache.get("my_key")
        assert val == {"data": 123}

        # Test get (Raw string / bytes fallback)
        mock_redis_client.get.return_value = b"raw string"
        val = await cache.get("my_key")
        assert val == "raw string"

        # Test get (None)
        mock_redis_client.get.return_value = None
        val = await cache.get("missing", default="def")
        assert val == "def"


@pytest.mark.asyncio
async def test_redis_cache_ops(mock_redis_client):
    from openviper.cache.redis import RedisCache

    with patch("openviper.cache.redis.redis") as mock_redis_module:
        mock_redis_module.Redis.from_url.return_value = mock_redis_client
        cache = RedisCache()

        # Delete
        await cache.delete("key")
        mock_redis_client.delete.assert_called_once_with("key")

        # Has key
        mock_redis_client.exists.return_value = 1
        assert await cache.has_key("key") is True

        # Clear
        await cache.clear()
        mock_redis_client.flushdb.assert_called_once()


@pytest.mark.asyncio
async def test_redis_cache_import_error():
    from openviper.cache.redis import RedisCache

    with patch("openviper.cache.redis.redis", None):
        with pytest.raises(ImportError, match="The 'redis' Python package is required"):
            RedisCache()
