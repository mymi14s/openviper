"""Database utilities for OpenViper ORM."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.db.models import Model

# ── Per-event-loop lock factory ──────────────────────────────────────────────
# asyncio.Lock is bound to the event loop that created it.  Using a lock
# created on one loop from another raises "Task got Future attached to a
# different loop".  The helper below lazily creates one lock per running loop
# and falls back to a fresh lock when no loop is active.

_per_loop_locks: dict[int, asyncio.Lock] = {}
_fallback_lock: asyncio.Lock | None = None


def get_per_loop_lock(cache: dict[int, asyncio.Lock] | None = None) -> asyncio.Lock:
    """Return an ``asyncio.Lock`` scoped to the currently running event loop.

    When called from inside a running loop, the same lock is returned for
    all calls on that loop.  When no loop is running (e.g. during sync
    setup), a shared fallback lock is used instead.

    Args:
        cache: Optional dict to use as the per-loop store.  When omitted,
            the module-level ``_per_loop_locks`` dict is used.
    """
    global _fallback_lock
    store = cache if cache is not None else _per_loop_locks
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if _fallback_lock is None:
            _fallback_lock = asyncio.Lock()
        return _fallback_lock
    loop_id = id(loop)
    if loop_id not in store:
        store[loop_id] = asyncio.Lock()
    return store[loop_id]


# ── PK type casting ──────────────────────────────────────────────────────────


def cast_to_pk_type(model_class: type[Model], value: Any) -> Any:
    """Cast a value to the type of the model's primary key.

    Args:
        model_class: The model class to check.
        value: The value to cast.

    Returns:
        The value cast to the primary key's Python type.
    """
    if value is None:
        return None

    pk_field = next(
        (
            f
            for f in getattr(model_class, "_fields", {}).values()
            if getattr(f, "primary_key", False)
        ),
        None,
    )

    if pk_field and hasattr(pk_field, "to_python"):
        try:
            return pk_field.to_python(value)
        except ValueError, TypeError:
            return value

    return value
