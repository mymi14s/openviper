"""In-process TTL cache for authenticated user objects.

Kept in a separate, import-light module so that both
``openviper.auth.authentications`` and ``openviper.auth.models`` can import
from here without triggering a circular dependency.

All cache mutations are guarded by an asyncio.Lock to prevent concurrent
coroutines from corrupting the dict under high load.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from openviper.auth.cache_utils import lazy_async_lock

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable

USER_CACHE: dict[int | str, tuple[Authenticable | None, float]] = {}
_USER_CACHE_LOCK_REF: list[asyncio.Lock | None] = [None]
LOCK_INIT_GUARD = threading.Lock()


def get_user_cache_lock() -> asyncio.Lock:
    """Return the module-level user cache lock, creating it lazily."""
    return lazy_async_lock(_USER_CACHE_LOCK_REF, LOCK_INIT_GUARD)


async def invalidate_user_cache(user_id: int) -> None:
    """Evict a user from the in-process TTL cache immediately.

    Call this whenever a User record is updated so that the next authenticated
    request performs a fresh DB lookup rather than serving a stale object.
    """
    lock = get_user_cache_lock()
    async with lock:
        USER_CACHE.pop(user_id, None)
