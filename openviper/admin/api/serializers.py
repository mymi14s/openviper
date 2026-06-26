"""Serializers for admin API responses.

Provides serialization utilities for converting model instances
to JSON-compatible dictionaries.
"""

from __future__ import annotations

import typing as t
from typing import TYPE_CHECKING

from openviper.admin.fields import get_field_schema

if TYPE_CHECKING:
    from openviper.admin.options import ModelAdmin
    from openviper.db.models import Model


def serialize_instance(
    instance: Model,
    model_admin: ModelAdmin,
    include_fields: list[str] | None = None,
) -> dict[str, t.Any]:
    """Serialize a model instance to a dictionary.

    Sensitive fields (e.g. password, token) are excluded from the output.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.
        include_fields: Optional list of fields to include.

    Returns:
        Dictionary with serialized field values.
    """
    fields = getattr(instance.__class__, "_fields", {})
    sensitive = set(model_admin.get_sensitive_fields())
    password_fields = model_admin.get_masked_fields()
    result = {"id": getattr(instance, "id", None)}

    field_names = include_fields or list(fields.keys())

    for field_name in field_names:
        if field_name in sensitive:
            continue
        if field_name in password_fields:
            result[field_name] = "****"
            continue
        result[field_name] = serialize_value(getattr(instance, field_name, None))

    return result


def serialize_value(value: t.Any) -> t.Any:
    """Serialize a field value for JSON.

    Args:
        value: The value to serialize.

    Returns:
        JSON-compatible value.
    """
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]

    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}

    # Money instances expose amount (Decimal) and currency (Currency with .code).
    # Check before as_tuple since Money may delegate to Decimal's attributes.
    # Normalize trailing zeros so 100.0000 displays as 100, not 100.0000.
    amount = getattr(value, "amount", None)
    currency = getattr(value, "currency", None)
    if amount is not None and currency is not None and hasattr(currency, "code"):
        normalized = amount.normalize()
        sign, digits, exponent = normalized.as_tuple()
        if isinstance(exponent, int) and exponent <= 0:
            return str(normalized)
        return str(int(normalized))

    if hasattr(value, "hex"):
        return str(value)

    if hasattr(value, "as_tuple"):
        return float(value)

    return str(value)


def serialize_for_list(
    instance: Model,
    model_admin: ModelAdmin,
) -> dict[str, t.Any]:
    """Serialize a model instance for list view.

    Only includes fields from list_display.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with list_display field values.
    """
    list_display = model_admin.get_list_display()
    password_fields = model_admin.get_masked_fields()
    result = {"id": getattr(instance, "id", None)}

    for field_name in list_display:
        if field_name in password_fields:
            result[field_name] = "****"
            continue
        value = getattr(instance, field_name, None)
        result[field_name] = serialize_value(value)

    return result


def serialize_for_detail(
    instance: Model,
    model_admin: ModelAdmin,
) -> dict[str, t.Any]:
    """Serialize a model instance for detail view.

    Includes all fields except sensitive ones, plus metadata.

    Args:
        instance: The model instance.
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with all field values and metadata.
    """
    fields = getattr(instance.__class__, "_fields", {})
    return serialize_instance(instance, model_admin, include_fields=list(fields.keys()))


def serialize_model_info(model_admin: ModelAdmin) -> dict[str, t.Any]:
    """Serialize model admin metadata.

    Args:
        model_admin: The ModelAdmin configuration.

    Returns:
        Dictionary with model metadata.
    """
    return model_admin.get_model_info()


def serialize_field_info(field: t.Any) -> dict[str, t.Any]:
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

    def serialize(self, instances: list[Model]) -> list[dict[str, t.Any]]:
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

    def serialize(self, instance: Model) -> dict[str, t.Any]:
        """Serialize a single instance.

        Args:
            instance: The model instance.

        Returns:
            Serialized dictionary.
        """
        return serialize_for_detail(instance, self.model_admin)
