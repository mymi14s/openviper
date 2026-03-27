"""In-process TTL cache for authenticated user objects.

Kept in a separate, import-light module so that both
``openviper.auth.authentications`` and ``openviper.auth.models`` can import
from here without triggering a circular dependency.
"""

from __future__ import annotations

from typing import Any

_USER_CACHE: dict[int, tuple[Any, float]] = {}


def invalidate_user_cache(user_id: Any) -> None:
    """Evict a user from the in-process TTL cache immediately.

    Call this whenever a User record is updated so that the next authenticated
    request performs a fresh DB lookup rather than serving a stale object.
    """
    _USER_CACHE.pop(user_id, None)
