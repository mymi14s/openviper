import asyncio
from unittest.mock import MagicMock, patch

import pytest

from openviper.cache import InMemoryCache, get_cache
from openviper.cache.base import BaseCache


@pytest.mark.asyncio
async def test_in_memory_cache_basic_ops():
    cache = InMemoryCache()

    # Set and Get
    await cache.set("foo", "bar")
    assert await cache.get("foo") == "bar"

    # Has Key
    assert await cache.has_key("foo") is True
    assert await cache.has_key("missing") is False

    # Delete
    await cache.delete("foo")
    assert await cache.get("foo") is None
    assert await cache.has_key("foo") is False

    # Default value
    assert await cache.get("missing", "default") == "default"


@pytest.mark.asyncio
async def test_in_memory_cache_ttl():
    cache = InMemoryCache()

    # Set with short TTL
    await cache.set("temp", "value", ttl=1)
    assert await cache.get("temp") == "value"

    # Wait for expiry
    await asyncio.sleep(1.1)
    assert await cache.get("temp") is None
    assert await cache.has_key("temp") is False


@pytest.mark.asyncio
async def test_in_memory_cache_clear():
    cache = InMemoryCache()
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")

    await cache.clear()
    assert await cache.get("k1") is None
    assert await cache.get("k2") is None


@pytest.mark.asyncio
async def test_get_cache_factory():
    # Reset singleton for testing
    import openviper.cache

    openviper.cache._cache_instance = None

    mock_settings = MagicMock()
    mock_settings.CACHE_BACKEND = "memory"

    with patch("openviper.cache.settings", mock_settings):
        cache1 = get_cache()
        assert isinstance(cache1, InMemoryCache)

        cache2 = get_cache()
        assert cache1 is cache2  # Singleton check


@pytest.mark.asyncio
async def test_get_cache_custom_backend():
    # Reset singleton for testing
    import openviper.cache

    openviper.cache._cache_instance = None

    # Mock a custom backend
    mock_backend = MagicMock(spec=BaseCache)
    mock_cls = MagicMock(return_value=mock_backend)

    mock_settings = MagicMock()
    mock_settings.CACHE_BACKEND = "myapp.cache.MyCache"

    with patch("openviper.cache.settings", mock_settings):
        with patch("openviper.cache.import_string", return_value=mock_cls):
            cache = get_cache()
            assert cache is mock_backend
