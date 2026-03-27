.. _cache:

Cache Framework
===============

OpenViper provides a simple, robust caching abstraction that can be used directly or within your routing and background task layers. The core cache interacts asynchronously with the underlying store, ensuring non-blocking operations.

Getting Started
---------------

The simplest way to use the cache is to import the ``get_cache`` factory. It will automatically load the backend configured in your settings.

.. code-block:: python

    from openviper.cache import get_cache

    async def my_view(request):
        cache = get_cache()

        # Check if we have cached data
        if await cache.has_key("my_expensive_data"):
            return await cache.get("my_expensive_data")

        # Compute and cache
        data = await compute_expensive_data()
        await cache.set("my_expensive_data", data, ttl=300) # cache for 5 minutes

        return data

Configuration
-------------

By default, OpenViper uses an in-memory cache. You can configure a different backend in your ``settings.py``:

.. code-block:: python

    # Use the local memory cache (default)
    CACHE_BACKEND = "memory"

    # Use Redis
    CACHE_BACKEND = "redis"
    REDIS_URL = "redis://localhost:6379"

Built-in Backends
-----------------

InMemoryCache
~~~~~~~~~~~~~
The default cache. Stores data in a Python dictionary. Suitable for local development or single-process deployments without critical cache persistence needs.

RedisCache
~~~~~~~~~~
A production-ready asynchronous Redis backend.

**Requirements**: You must install the `redis` library (e.g., ``pip install openviper[redis]`` or ``pip install redis``).

.. code-block:: python

    # settings.py
    CACHE_BACKEND = "redis"
    REDIS_URL = "redis://user:password@redis-host:6379/0"

The RedisCache will automatically serialize and deserialize dictionaries and lists to and from JSON.

Creating Custom Backends
------------------------

If you need to store your cache in a different system (like Memcached, a Database table, or AWS ElastiCache), you can easily build a custom backend.

1. Create a class that inherits from ``openviper.cache.base.BaseCache``.
2. Implement the required async methods: ``get``, ``set``, ``delete``, ``has_key``, and ``clear``.

.. code-block:: python

    # myapp/cache.py
    from typing import Any
    from openviper.cache.base import BaseCache

    class FileSystemCache(BaseCache):
        def __init__(self, directory: str = "/tmp/cache"):
            self.dir = directory
            # ... initialize directory

        async def get(self, key: str, default: Any = None) -> Any:
            # ... read from file
            pass

        async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
            # ... write to file
            pass

        async def delete(self, key: str) -> None:
            pass

        async def has_key(self, key: str) -> bool:
            pass

        async def clear(self) -> None:
            pass

3. Point your settings to the custom backend using a dotted module path:

.. code-block:: python

    # settings.py
    CACHE_BACKEND = "myapp.cache.FileSystemCache"

When ``get_cache()`` is called, OpenViper will dynamically import and instantiate your class.
