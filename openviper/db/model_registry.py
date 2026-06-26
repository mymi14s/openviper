"""Shared registry and cache state for DB modules with circular imports."""

from __future__ import annotations

from collections.abc import Callable

# Model registry: populated by ModelMeta.
registry: dict[str, type] = {}

# Secondary name index: simple class name -> list of model classes.
name_index: dict[str, list[type]] = {}

# Soft-removed column cache: populated by load_soft_removed_columns.
soft_removed_cache: dict[str, frozenset[str]] = {}
soft_removed_loaded: bool = False

# Set after ModelMeta; used for M2M auto-through creation.
model_meta_cls: type | None = None

# Set after Model; base for auto-through models.
model_cls: type | None = None

# Set after QuerySet; used for ReverseRelationDescriptor.
queryset_cls: type | None = None

table_cache_callbacks: list[Callable[[], None]] = []

rebuild_all_tables_callback: Callable[[], None] | None = None


def invalidate_table_cache() -> None:
    """Clear all cached SQLAlchemy Table definitions.

    Each registered callback typically wraps a ``functools.lru_cache``
    ``cache_clear`` call so that the next ``get_table`` rebuilds the table
    with the currently configured settings.
    """
    for callback in table_cache_callbacks:
        callback()


def rebuild_all_tables() -> None:
    """Clear cached table definitions and rebuild all tables from the registry.

    This ensures FK targets are re-resolved with the current settings
    (e.g. after ``USER_MODEL`` changes at test setup time).
    """
    invalidate_table_cache()
    if rebuild_all_tables_callback is not None:
        rebuild_all_tables_callback()


def invalidate_soft_removed_cache() -> None:
    """Clear the soft-removed column cache so the next query reloads from the DB."""
    global soft_removed_loaded
    soft_removed_cache.clear()
    soft_removed_loaded = False
