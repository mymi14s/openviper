"""Shared registry and cache state for DB modules with circular imports."""

from __future__ import annotations

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


def invalidate_soft_removed_cache() -> None:
    """Clear the soft-removed column cache so the next query reloads from the DB."""
    global soft_removed_loaded
    soft_removed_cache.clear()
    soft_removed_loaded = False
