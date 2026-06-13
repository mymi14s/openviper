"""Shared constants and helpers for the database package.

Centralises repeated ``getattr`` / ``hasattr`` patterns so that a single
source of truth is maintained across the ORM.
"""

from __future__ import annotations

import typing as t


def get_model_fields(model_class: type) -> dict[str, t.Any]:
    """Return the ``_fields`` mapping from a model class.

    Consolidates the repeated ``getattr(model_class, "_fields", {})``
    pattern across the database module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The field name to field instance mapping.
    """
    return getattr(model_class, "_fields", {})


def has_model_fields(model_class: type) -> bool:
    """Return whether *model_class* has a ``_fields`` attribute.

    Consolidates the repeated ``hasattr(model_class, "_fields")`` pattern.

    Args:
        model_class: The model class to inspect.

    Returns:
        ``True`` if the model defines ``_fields``.
    """
    return hasattr(model_class, "_fields")


def get_model_meta(model_class: type) -> t.Any:
    """Return the ``_meta`` object from a model class, or ``None``.

    Consolidates the repeated ``getattr(model_class, "_meta", None)``
    pattern across the database module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The ``_meta`` namespace if present, otherwise ``None``.
    """
    return getattr(model_class, "_meta", None)


def get_app_label(model_class: type) -> str:
    """Return the app label for a model class.

    Checks ``_meta.app_label`` first, then falls back to the
    ``_app_name`` attribute, defaulting to ``"default"``.

    Args:
        model_class: The model class to inspect.

    Returns:
        The app label string.
    """
    meta = get_model_meta(model_class)
    if meta is not None:
        app_label = getattr(meta, "app_label", None)
        if isinstance(app_label, str):
            return app_label
    return getattr(model_class, "_app_name", "default")


def get_table_name(model_class: type) -> str:
    """Return the table name for a model class.

    Falls back to the lower-cased class name if ``_table_name`` is absent.

    Args:
        model_class: The model class to inspect.

    Returns:
        The table name string.
    """
    return getattr(model_class, "_table_name", model_class.__name__.lower())


def has_table_name(model_class: type) -> bool:
    """Return whether *model_class* has a ``_table_name`` attribute.

    Consolidates the repeated ``hasattr(model_class, "_table_name")`` pattern.

    Args:
        model_class: The model class to inspect.

    Returns:
        ``True`` if the model defines ``_table_name``.
    """
    return hasattr(model_class, "_table_name")
