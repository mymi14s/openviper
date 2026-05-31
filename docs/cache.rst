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

By default, OpenViper uses an in-memory cache. You can configure backends
via the ``CACHES`` dict in ``settings.py``:

.. code-block:: python

    CACHES = {
        "default": {
            "BACKEND": "openviper.cache.InMemoryCache",
        },
        "redis": {
            "BACKEND": "openviper.cache.RedisCache",
            "OPTIONS": {"url": "redis://localhost:6379/0"},
        },
    }

Thread-safe singleton access is guaranteed via an internal lock.

Built-in Backends
-----------------

InMemoryCache
~~~~~~~~~~~~~
The default cache. Stores data in a Python dictionary. Suitable for local development or single-process deployments without critical cache persistence needs.

RedisCache
~~~~~~~~~~
A production-ready asynchronous Redis backend.

**Requirements**: You must install the ``redis`` library (e.g., ``pip install openviper[tasks]`` or ``pip install redis``).

.. code-block:: python

    # settings.py
    CACHE_BACKEND = "redis"
    REDIS_URL = "redis://user:password@redis-host:6379/0"

The RedisCache will automatically serialize and deserialize dictionaries and lists to and from JSON.

DatabaseCache
~~~~~~~~~~~~~
A database-backed cache using the OpenViper ORM.  Values are serialized with
orjson and stored in the ``openviper_cache_entries`` table.

.. code-block:: python

    CACHES = {
        "db": {
            "BACKEND": "openviper.cache.DatabaseCache",
        },
    }

Supports PostgreSQL (``INSERT ... ON CONFLICT`` upsert), SQLite (``INSERT OR
REPLACE``), and a fallback ORM-based upsert for other dialects.  Expired
entries are lazily cleaned up on access.

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

API Reference
-------------

``openviper.cache``
~~~~~~~~~~~~~~~~~~~~

.. py:function:: get_cache(alias="default") -> BaseCache

   Return the cache backend for the given alias, creating it on first access.
   Instances are stored in ``cache_instances`` and reused on subsequent calls.
   Thread-safe via ``cache_lock``.

   * ``"default"`` alias with no ``CACHES`` setting returns an
     ``InMemoryCache``.
   * Unknown non-default aliases raise ``ValueError``.

.. py:data:: cache_instances

   Module-level ``dict[str, BaseCache]`` holding instantiated backends.
   Populated by :func:`get_cache`.

.. py:data:: cache_lock

   ``threading.Lock`` guarding concurrent access to :data:`cache_instances`.

``openviper.cache.base``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: BaseCache

   Abstract base class for all cache backends.  Concrete subclasses
   **must** call ``validate_cache_key(key)`` before any operation.

   .. py:method:: async get(key, default=None) -> Any

      Fetch a value from the cache.  Return *default* on miss.

   .. py:method:: async set(key, value, ttl=None) -> None

      Store a value.  *ttl* is time-to-live in seconds; ``None`` means no
      expiry.

   .. py:method:: async delete(key) -> None

      Remove a value from the cache.

   .. py:method:: async clear() -> None

      Remove all values from the cache.

   .. py:method:: async has_key(key) -> bool

      Check whether a key exists.  Default calls ``get()`` and checks for
      ``None``; backends with a cheaper existence check should override.

   .. py:method:: async keys(prefix="") -> list[str]

      Return all cache keys, optionally filtered by *prefix*.  Default
      returns ``[]``; backends that can enumerate keys should override.

``openviper.cache.memory``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: InMemoryCache(BaseCache)

   In-memory cache backed by a ``dict``.  Thread-safe for concurrent async
   access via an ``asyncio.Lock``.  When no *ttl* is provided to ``set()``,
   ``settings.CACHE_TTL`` is used as the default.

``openviper.cache.redis``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: RedisCache(BaseCache, *, key_prefix="ov:cache:", **kwargs)

   Redis-backed cache using ``redis.asyncio`` with orjson serialization.
   Requires the ``redis`` package (``pip install redis``).

   All keys are prefixed with *key_prefix* to isolate this cache from other
   data in the same Redis database.  ``clear()`` only deletes keys matching
   the prefix via ``SCAN`` + ``UNLINK`` - it never calls ``FLUSHDB``.

.. py:data:: DEFAULT_KEY_PREFIX

   Default Redis key prefix: ``"ov:cache:"``.

``openviper.cache.db_backend``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: DatabaseCache(BaseCache)

   Database-backed cache using the OpenViper ORM with orjson serialization.
   Supports PostgreSQL (``INSERT ... ON CONFLICT``), SQLite (``INSERT OR
   REPLACE``), and a fallback ORM-based upsert for other dialects.

.. py:function:: is_entry_expired(expires_at) -> bool

   Return ``True`` when *expires_at* is in the past relative to ``now()``.
   Handles timezone-aware/naive mismatches by converting to a common
   timezone before comparison.

.. py:function:: validate_table_name(name) -> str

   Validate that *name* is a safe SQL identifier matching
   ``^[a-zA-Z_][a-zA-Z0-9_]*$``.  Raises ``ValueError`` on invalid input.

.. py:data:: SAFE_TABLE_RE

   Compiled regex pattern used by :func:`validate_table_name`.

``openviper.cache.db``
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CacheEntry(Model)

   ORM model for database-backed cache storage.

   .. py:attribute:: key

      ``CharField(max_length=512, unique=True)``

   .. py:attribute:: value

      ``TextField``

   .. py:attribute:: expires_at

      ``DateTimeField(null=True)``

``openviper.cache.validation``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: validate_cache_key(key) -> str

   Validate and return a cache key.  Raises ``ValueError`` if the key is
   empty, exceeds ``CACHE_KEY_MAX_LEN`` characters, or contains whitespace.

.. py:data:: CACHE_KEY_MAX_LEN

   Maximum allowed cache key length: ``250``.

.. py:data:: CACHE_KEY_RE

   Compiled regex ``^\\S+$`` used to reject whitespace in cache keys.
