"""Field type mapping for admin panel.

Maps OpenViper model fields to frontend component types and configurations
for dynamic form rendering.
"""

from __future__ import annotations

import importlib
import json
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.db.fields import Field


# Mapping of field class names to Vue component types
FIELD_COMPONENT_MAP: dict[str, str] = {
    "AutoField": "hidden",
    "IntegerField": "number",
    "BigIntegerField": "number",
    "PositiveIntegerField": "number",
    "FloatField": "number",
    "DecimalField": "number",
    "CharField": "text",
    "TextField": "textarea",
    "EmailField": "email",
    "URLField": "url",
    "BooleanField": "checkbox",
    "DateField": "date",
    "DateTimeField": "datetime",
    "TimeField": "time",
    "UUIDField": "text",
    "JSONField": "json",
    "SlugField": "text",
    "IPAddressField": "text",
    "GenericIPAddressField": "text",
    "FileField": "file",
    "ImageField": "image",
    "ForeignKey": "foreignkey",
    "OneToOneField": "foreignkey",
    "ManyToManyField": "multiselect",
}


def get_field_component_type(field: Field) -> str:
    """Get the Vue component type for a field.

    Args:
        field: The model field instance.

    Returns:
        The component type string (e.g., 'text', 'number', 'select').
    """
    field_class_name = field.__class__.__name__
    return FIELD_COMPONENT_MAP.get(field_class_name, "text")


def get_field_widget_config(field: Field) -> dict[str, Any]:
    """Get widget configuration for a field.

    Args:
        field: The model field instance.

    Returns:
        Dict of widget configuration options.
    """
    config: dict[str, Any] = {}
    field_class_name = field.__class__.__name__

    # Common config
    config["required"] = not getattr(field, "null", True) and not getattr(field, "blank", True)
    config["readonly"] = field.__class__.__name__ == "AutoField"
    config["help_text"] = getattr(field, "help_text", "")

    # Choices
    if hasattr(field, "choices") and field.choices:
        config["choices"] = [{"value": c[0], "label": c[1]} for c in field.choices]

    # Field-specific config
    if field_class_name == "CharField":
        config["max_length"] = getattr(field, "max_length", 255)

    elif field_class_name in (
        "IntegerField",
        "BigIntegerField",
        "PositiveIntegerField",
    ):
        if field_class_name == "PositiveIntegerField":
            config["min"] = 0

    elif field_class_name == "FloatField":
        config["step"] = 0.01

    elif field_class_name == "DecimalField":
        decimal_places = getattr(field, "decimal_places", 2)
        config["step"] = 10**-decimal_places

    elif field_class_name == "TextField":
        config["rows"] = 5

    elif field_class_name == "DateTimeField":
        config["auto_now"] = getattr(field, "auto_now", False)
        config["auto_now_add"] = getattr(field, "auto_now_add", False)
        if config["auto_now"] or config["auto_now_add"]:
            config["readonly"] = True

    elif field_class_name == "UUIDField":
        config["readonly"] = True

    return config


def get_field_schema(field: Field) -> dict[str, Any]:
    """Get complete field schema for API response.

    Args:
        field: The model field instance.

    Returns:
        Dict with field type, component, and configuration.
    """
    field_class_name = field.__class__.__name__

    schema = {
        "name": getattr(field, "name", ""),
        "type": field_class_name,
        "component": get_field_component_type(field),
        "column_type": getattr(field, "_column_type", "TEXT"),
        "primary_key": getattr(field, "primary_key", False),
        "null": getattr(field, "null", False),
        "blank": getattr(field, "blank", False),
        "unique": getattr(field, "unique", False),
        "db_index": getattr(field, "db_index", False),
        "default": _serialize_default(getattr(field, "default", None)),
        "config": get_field_widget_config(field),
    }

    # Add related model info for ForeignKey/OneToOneField
    if field_class_name in ("ForeignKey", "OneToOneField"):
        related_model = getattr(field, "to", None)
        if related_model:
            if isinstance(related_model, str):
                # String reference like "user.models.User" or "auth.User"
                # Try to resolve the actual model class to get its _app_name
                resolved_model = None
                parts = related_model.split(".")
                model_name = parts[-1]  # Last part is always model name

                # Try importing the model
                if len(parts) >= 2:
                    try:
                        # Try {parts[0]}.models pattern
                        module_path = f"{parts[0]}.models"
                        module = importlib.import_module(module_path)
                        resolved_model = getattr(module, model_name, None)
                    except (ImportError, AttributeError):
                        pass

                    # Try full module path (e.g., "user.models" for "user.models.User")
                    if resolved_model is None and len(parts) >= 3:
                        try:
                            module_path = ".".join(parts[:-1])
                            module = importlib.import_module(module_path)
                            resolved_model = getattr(module, model_name, None)
                        except (ImportError, AttributeError):
                            pass

                if resolved_model is not None:
                    # Got the actual model class - use its _app_name
                    app_name = getattr(
                        resolved_model,
                        "_app_name",
                        parts[0] if len(parts) >= 2 else "default",
                    )
                else:
                    # Fallback to parsing the string
                    app_name = parts[0] if len(parts) >= 2 else "default"

                schema["related_model"] = f"{app_name}/{model_name}"
            else:
                # Actual model class
                app_name = getattr(related_model, "_app_name", "default")
                model_name = related_model.__name__
                schema["related_model"] = f"{app_name}/{model_name}"

    return schema


def _serialize_default(default: Any) -> Any:
    """Serialize a default value for JSON.

    Args:
        default: The default value (may be callable).

    Returns:
        JSON-serializable representation.
    """
    if default is None:
        return None
    if callable(default):
        return "__callable__"
    if isinstance(default, (str, int, float, bool, list, dict)):
        return default
    return str(default)


def coerce_field_value(field: Field, value: Any) -> Any:
    """Coerce a value to the appropriate type for a field.

    Args:
        field: The model field instance.
        value: The value to coerce.

    Returns:
        The coerced value.
    """
    if value is None:
        return None

    field_class_name = field.__class__.__name__

    if field_class_name in ("IntegerField", "BigIntegerField", "PositiveIntegerField"):
        return int(value)

    elif field_class_name == "FloatField":
        return float(value)

    elif field_class_name == "DecimalField":
        return Decimal(str(value))

    elif field_class_name == "BooleanField":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")

    elif field_class_name == "DateField":
        if isinstance(value, str):
            return date.fromisoformat(value)
        return value

    elif field_class_name == "DateTimeField":
        if isinstance(value, str):
            # Handle ISO format with or without timezone
            value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value)
        return value

    elif field_class_name == "TimeField":
        if isinstance(value, str):
            return time.fromisoformat(value)
        return value

    elif field_class_name == "JSONField":
        if isinstance(value, str):
            return json.loads(value)
        return value

    elif field_class_name == "UUIDField":
        if isinstance(value, str):
            return uuid.UUID(value)
        return value

    return value
