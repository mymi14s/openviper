"""Serializers for admin API responses.

Provides serialization utilities for converting model instances
to JSON-compatible dictionaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.admin.fields import get_field_schema

if TYPE_CHECKING:
    from openviper.admin.options import ModelAdmin
    from openviper.db.models import Model


def serialize_instance(
    instance: Model,
    model_admin: ModelAdmin,
    include_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Serialize a model instance to a dictionary.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.
        include_fields: Optional list of fields to include.

    Returns:
        Dictionary with serialized field values.
    """
    fields = getattr(instance.__class__, "_fields", {})
    result = {"id": getattr(instance, "id", None)}

    field_names = include_fields or list(fields.keys())

    for field_name in field_names:
        value = getattr(instance, field_name, None)
        result[field_name] = serialize_value(value)

    return result


def serialize_value(value: Any) -> Any:
    """Serialize a field value for JSON.

    Args:
        value: The value to serialize.

    Returns:
        JSON-compatible value.
    """
    if value is None:
        return None

    # Datetime types
    if hasattr(value, "isoformat"):
        return value.isoformat()

    # Basic types
    if isinstance(value, (str, int, float, bool)):
        return value

    # Collections
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]

    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}

    # UUID
    if hasattr(value, "hex"):
        return str(value)

    # Decimal
    if hasattr(value, "as_tuple"):
        return float(value)

    # Fallback to string
    return str(value)


def serialize_for_list(
    instance: Model,
    model_admin: ModelAdmin,
) -> dict[str, Any]:
    """Serialize a model instance for list view.

    Only includes fields from list_display.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with list_display field values.
    """
    list_display = model_admin.get_list_display()
    result = {"id": getattr(instance, "id", None)}

    for field_name in list_display:
        value = getattr(instance, field_name, None)
        result[field_name] = serialize_value(value)

    return result


def serialize_for_detail(
    instance: Model,
    model_admin: ModelAdmin,
) -> dict[str, Any]:
    """Serialize a model instance for detail view.

    Includes all fields and metadata.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with all field values and metadata.
    """
    fields = getattr(instance.__class__, "_fields", {})
    result = {"id": getattr(instance, "id", None)}

    for field_name in fields:
        value = getattr(instance, field_name, None)
        result[field_name] = serialize_value(value)

    return result


def serialize_model_info(model_admin: ModelAdmin) -> dict[str, Any]:
    """Serialize model admin metadata.

    Args:
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with model metadata.
    """
    return model_admin.get_model_info()


def serialize_field_info(field: Any) -> dict[str, Any]:
    """Serialize field metadata.

    Args:
        field: The model field.

    Returns:
        Dictionary with field metadata.
    """
    return get_field_schema(field)


class ModelListSerializer:
    """Serializer for model list responses."""

    def __init__(self, model_admin: ModelAdmin) -> None:
        self.model_admin = model_admin

    def serialize(self, instances: list[Model]) -> list[dict[str, Any]]:
        """Serialize a list of instances.

        Args:
            instances: List of model instances.

        Returns:
            List of serialized dictionaries.
        """
        return [serialize_for_list(instance, self.model_admin) for instance in instances]


class ModelDetailSerializer:
    """Serializer for model detail responses."""

    def __init__(self, model_admin: ModelAdmin) -> None:
        self.model_admin = model_admin

    def serialize(self, instance: Model) -> dict[str, Any]:
        """Serialize a single instance.

        Args:
            instance: The model instance.

        Returns:
            Serialized dictionary.
        """
        return serialize_for_detail(instance, self.model_admin)
