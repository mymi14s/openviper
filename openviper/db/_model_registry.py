"""Shared registry and cache state for DB modules with circular imports."""

from __future__ import annotations

# Model registry: populated by ModelMeta in models.py.
# Maps "app.ModelName" -> model class.
registry: dict[str, object] = {}

# Secondary name index: simple class name -> list of model classes.
name_index: dict[str, list[object]] = {}

# Soft-removed column cache: populated by load_soft_removed_columns in executor.py.
soft_removed_cache: dict[str, frozenset[str]] = {}
soft_removed_loaded: bool = False

# Set by models.py after ModelMeta is defined; used by fields.py for M2M auto-through creation.
model_meta_cls: object | None = None

# Set by models.py after Model is defined; used by fields.py as the base for auto-through models.
model_cls: object | None = None

# Set by models.py after QuerySet is defined; used by fields.py for ReverseRelationDescriptor.
queryset_cls: object | None = None


def invalidate_soft_removed_cache() -> None:
    """Clear the soft-removed column cache so the next query reloads from the DB."""
    global soft_removed_loaded
    soft_removed_cache.clear()
    soft_removed_loaded = False
