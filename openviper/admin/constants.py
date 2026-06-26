"""Shared constants and helpers for the admin package.

Centralises values that are referenced across multiple admin modules
so that a single source of truth is maintained.
"""

from __future__ import annotations

import typing as t

SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "secret",
        "key",
        "api_key",
        "access_token",
        "refresh_token",
    },
)
"""Field-name substrings that flag a field as sensitive.

Used by ``ModelAdmin.get_sensitive_fields`` and ``history`` masking
to ensure both modules apply the same policy.
"""

MIN_PASSWORD_LENGTH: int = 8
"""Minimum length enforced for admin password changes."""

MIN_PASSWORD_LENGTH_MSG: str = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
"""Pre-formatted message for password-length validation errors."""

PASSWORD_MISMATCH_MSG: str = "Passwords do not match."  # noqa: S105
"""Standard message for password confirmation mismatch."""

USER_NOT_FOUND_MSG: str = "User not found."
"""Standard message for user-not-found errors."""


def is_admin_user(user: object) -> bool:
    """Return ``True`` if *user* has staff or superuser privileges.

    Safely handles objects that lack ``is_staff`` or ``is_superuser``
    attributes by falling back to ``False``.
    """
    return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)


def get_model_fields(model_class: type) -> dict[str, t.Any]:
    """Return the ``_fields`` mapping from a model class.

    Provides a safe fallback to an empty dict when the attribute is
    absent, consolidating the repeated ``getattr(model_class, "_fields", {})``
    pattern across the admin module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The field name to field instance mapping.
    """
    return getattr(model_class, "_fields", {})


def get_model_meta(model_class: type) -> t.Any:
    """Return the ``_meta`` object from a model class, or ``None``.

    Consolidates the repeated ``getattr(model_class, "_meta", None)``
    pattern across the admin module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The ``_meta`` namespace if present, otherwise ``None``.
    """
    return getattr(model_class, "_meta", None)


def get_app_label(model_class: type) -> str:
    """Return the app label for a model class.

    Checks ``Meta.app_label`` first, then falls back to the
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
    if hasattr(model_class, "Meta") and hasattr(model_class.Meta, "app_label"):
        app_label = model_class.Meta.app_label
        if isinstance(app_label, str):
            return app_label
    return getattr(model_class, "_app_name", "default")
