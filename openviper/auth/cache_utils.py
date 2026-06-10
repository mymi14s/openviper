"""Shared cache and table-ensure utilities for the auth module.

Eliminates duplicated lazy-lock initialisation, cache eviction, and
table-ensure patterns across ``authentications``, ``token_blocklist``,
``_user_cache``, and ``session.utils``.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlalchemy as sa

from openviper.db.connection import get_engine


def lazy_async_lock(
    lock_ref: list[asyncio.Lock | None],
    guard: threading.Lock,
) -> asyncio.Lock:
    """Return a lazily-created ``asyncio.Lock`` using double-checked locking.

    *lock_ref* must be a mutable one-element list ``[None]`` that stores the
    created lock.  The *guard* is a ``threading.Lock`` serialising the
    one-time creation across threads.
    """
    if lock_ref[0] is None:
        with guard:
            if lock_ref[0] is None:
                lock_ref[0] = asyncio.Lock()
    lock = lock_ref[0]
    if lock is None:
        raise RuntimeError("Async lock initialization failed.")
    return lock


def evict_cache_if_full[K, V](
    cache: dict[K, V],
    maxsize: int,
    now: float,
    expiry_extractor: Callable[[V], float],
    batch_fraction: float = 0.1,
) -> None:
    """Evict stale then oldest entries when *cache* exceeds *maxsize*.

    Must be called while the cache lock is already held.

    Args:
        cache: The dict-based TTL cache to trim.
        maxsize: Maximum number of entries before eviction triggers.
        now: Current monotonic time used to identify stale entries.
        expiry_extractor: Function extracting the expiry timestamp from a
            cache value (e.g. ``lambda v: v[1]`` for ``(user, exp)`` tuples).
        batch_fraction: Fraction of *maxsize* to evict per call (default 0.1).
    """
    if len(cache) <= maxsize:
        return
    batch = max(1, int(maxsize * batch_fraction))
    stale = [k for k, v in cache.items() if expiry_extractor(v) < now][:batch]
    if not stale:
        stale = list(cache.keys())[:batch]
    for k in stale:
        del cache[k]


async def ensure_table(
    table: sa.Table,
    ensured_flag: list[bool],
    ensure_lock: asyncio.Lock,
    suppress_errors: tuple[type[Exception], ...] | None = None,
) -> None:
    """Create *table* in the database if it does not yet exist.

    Uses a double-checked locking pattern with *ensured_flag* (a mutable
    one-element list ``[False]``) and *ensure_lock* to guarantee at most
    one DDL round-trip per process lifetime.

    When *suppress_errors* is provided, any exception matching those types
    during DDL execution is silently swallowed.
    """
    if ensured_flag[0]:
        return
    async with ensure_lock:
        if ensured_flag[0]:
            return
        engine = await get_engine()
        if suppress_errors:
            with contextlib.suppress(*suppress_errors):
                async with engine.begin() as conn:
                    await conn.run_sync(table.create, checkfirst=True)
        else:
            async with engine.begin() as conn:
                await conn.run_sync(table.create, checkfirst=True)
        ensured_flag[0] = True
