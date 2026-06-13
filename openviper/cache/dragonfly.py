"""Dragonfly-backed cache implementation using redis.asyncio with orjson serialization.

Dragonfly is a modern in-memory data store that is a drop-in replacement for
Redis, offering significantly higher throughput and lower latency.  Because
Dragonfly speaks the Redis protocol, this backend uses the same ``redis.asyncio``
client library but provides Dragonfly-specific defaults and documentation.
"""

from __future__ import annotations

from typing import Any

from openviper.cache.redis import RedisCache

DEFAULT_KEY_PREFIX: str = "ov:df:"


class DragonflyCache(RedisCache):
    """Dragonfly-backed cache using redis.asyncio with orjson serialization.

    Requires the ``redis`` package to be installed (Dragonfly speaks the
    Redis protocol).  Install it with: ``pip install redis``

    All keys are prefixed with ``key_prefix`` (default ``"ov:df:"``) to
    isolate this cache from other data in the same Dragonfly instance.
    The ``clear()`` method only deletes keys matching the prefix - it
    never calls ``FLUSHDB``.

    Dragonfly offers higher multi-threaded throughput compared to Redis,
    making this backend ideal for high-concurrency workloads.
    """

    def __init__(
        self,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialise the Dragonfly cache with connection parameters."""
        super().__init__(key_prefix=key_prefix, host=host, port=port, db=db, **kwargs)


__all__ = ["DragonflyCache"]
