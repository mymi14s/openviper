"""Database utilities for OpenViper ORM."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.db.models import Model


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

    # Find the primary key field
    pk_field = None
    fields = getattr(model_class, "_fields", {})
    for field in fields.values():
        if getattr(field, "primary_key", False):
            pk_field = field
            break

    if pk_field and hasattr(pk_field, "to_python"):
        try:
            return pk_field.to_python(value)
        except ValueError, TypeError:
            # Fallback to original value if casting fails
            return value

    return value


class ClassProperty:
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        return self.func(owner)
