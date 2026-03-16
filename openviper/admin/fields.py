"""Field type mapping for admin panel.

Maps OpenViper model fields to frontend component types and configurations
for dynamic form rendering.
"""

from __future__ import annotations

import functools
import importlib
import json
import logging
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.db.fields import Field

logger = logging.getLogger(__name__)

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

    if (
        field_class_name
        in (
            "IntegerField",
            "BigIntegerField",
            "PositiveIntegerField",
        )
        and field_class_name == "PositiveIntegerField"
    ):
        config["min"] = 0

    if field_class_name == "FloatField":
        config["step"] = 0.01

    if field_class_name == "DecimalField":
        decimal_places = getattr(field, "decimal_places", 2)
        config["step"] = 10**-decimal_places

    if field_class_name == "TextField":
        config["rows"] = 5

    if field_class_name == "DateTimeField":
        config["auto_now"] = getattr(field, "auto_now", False)
        config["auto_now_add"] = getattr(field, "auto_now_add", False)
        if config["auto_now"] or config["auto_now_add"]:
            config["readonly"] = True

    if field_class_name == "UUIDField":
        config["readonly"] = True

    if field_class_name in ("FileField", "ImageField"):
        config["upload_to"] = getattr(field, "upload_to", "uploads/")
        max_size = getattr(field, "_max_file_size", None)
        if max_size:
            config["max_file_size"] = max_size
        if field_class_name == "ImageField":
            allowed_ext = getattr(field, "allowed_extensions", None)
            if allowed_ext:
                config["allowed_extensions"] = list(allowed_ext)

    return config


@functools.lru_cache(maxsize=512)
def _get_field_schema_cached(
    field_class_name: str,
    field_name: str,
    column_type: str,
    primary_key: bool,
    null: bool,
    blank: bool,
    unique: bool,
    db_index: bool,
    default_str: str,
    related_model_str: str | None,
) -> dict[str, Any]:
    """Cached version of field schema computation.

    Args:
        field_class_name: The field class name.
        field_name: The field name.
        column_type: The column type.
        primary_key: Whether this is a primary key.
        null: Whether null is allowed.
        blank: Whether blank is allowed.
        unique: Whether this field is unique.
        db_index: Whether this field has an index.
        default_str: String representation of default value.
        related_model_str: String representation of related model.

    Returns:
        Dict with field type, component, and configuration.
    """
    # Reconstruct the schema from cached parameters
    schema = {
        "name": field_name,
        "type": field_class_name,
        "component": FIELD_COMPONENT_MAP.get(field_class_name, "text"),
        "column_type": column_type,
        "primary_key": primary_key,
        "null": null,
        "blank": blank,
        "unique": unique,
        "db_index": db_index,
        "default": None if default_str == "__none__" else default_str,
    }

    if related_model_str:
        schema["related_model"] = related_model_str

    return schema


def get_field_schema(field: Field) -> dict[str, Any]:
    """Get complete field schema for API response.

    Args:
        field: The model field instance.

    Returns:
        Dict with field type, component, and configuration.
    """
    field_class_name = field.__class__.__name__

    # Extract cacheable parameters
    field_name = getattr(field, "name", "")
    column_type = getattr(field, "_column_type", "TEXT")
    primary_key = getattr(field, "primary_key", False)
    null = getattr(field, "null", False)
    blank = getattr(field, "blank", False)
    unique = getattr(field, "unique", False)
    db_index = getattr(field, "db_index", False)

    default = getattr(field, "default", None)
    default_str = "__none__" if default is None else _serialize_default(default)

    # Handle related model
    related_model_str = None
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
                    except ImportError, AttributeError:
                        pass

                    # Try full module path (e.g., "user.models" for "user.models.User")
                    if resolved_model is None and len(parts) >= 3:
                        try:
                            module_path = ".".join(parts[:-1])
                            module = importlib.import_module(module_path)
                            resolved_model = getattr(module, model_name, None)
                        except ImportError, AttributeError:
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

                related_model_str = f"{app_name}/{model_name}"
            else:
                # Actual model class
                app_name = getattr(related_model, "_app_name", "default")
                model_name = related_model.__name__
                related_model_str = f"{app_name}/{model_name}"

    # Get cached schema
    schema = _get_field_schema_cached(
        field_class_name,
        field_name,
        column_type,
        primary_key,
        null,
        blank,
        unique,
        db_index,
        default_str,
        related_model_str,
    )

    # Add widget config (not cached as it may have dynamic choices)
    schema["config"] = get_field_widget_config(field)

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
    if isinstance(default, (list, dict)):
        try:
            return json.dumps(default)
        except TypeError:
            return str(default)
    if isinstance(default, (str, int, float, bool)):
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
    field_name = getattr(field, "name", "unknown")
    field_class_name = field.__class__.__name__

    # Handle '__callable__' sentinel from frontend for auto-generated fields
    if value == "__callable__":
        is_auto = getattr(field, "auto", False) or getattr(field, "auto_increment", False)
        if is_auto:
            return None
        raise ValueError(f"Field {field_name} received invalid sentinel value '__callable__'")

    if value is None:
        return None

    # Handle empty strings for numeric and relational fields - usually means null/not set
    if value == "" and (
        field_class_name
        in (
            "IntegerField",
            "BigIntegerField",
            "PositiveIntegerField",
            "FloatField",
            "DecimalField",
            "ForeignKey",
            "OneToOneField",
        )
        or getattr(field, "null", False)
    ):
        return None

    try:
        if field_class_name in ("IntegerField", "BigIntegerField", "PositiveIntegerField"):
            return int(value)

        if field_class_name == "FloatField":
            return float(value)

        if field_class_name == "DecimalField":
            return Decimal(str(value))

        if field_class_name == "BooleanField":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")

        if field_class_name == "DateField":
            if isinstance(value, str):
                return date.fromisoformat(value)
            return value

        if field_class_name == "DateTimeField":
            if isinstance(value, str):
                # Handle ISO format with or without timezone
                value = value.replace("Z", "+00:00")
                return datetime.fromisoformat(value)
            return value

        if field_class_name == "TimeField":
            if isinstance(value, str):
                return time.fromisoformat(value)
            return value

        if field_class_name == "JSONField":
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON format: {str(exc)}") from exc
            return value

        if field_class_name == "UUIDField":
            if value == "":
                return None
            if isinstance(value, uuid.UUID):
                return value
            if isinstance(value, str):
                return uuid.UUID(value)
            return value

        if field_class_name in ("ForeignKey", "OneToOneField"):
            # FK columns may reference integer, UUID, or string PKs — preserve type.
            if isinstance(value, str) and value.isdigit():
                return int(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
            # UUID string or other non-integer PK (e.g. CharField PK) — pass through
            return value

    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning(
            "Field coercion failed for %s (%s): value=%r, error=%s",
            field_name,
            field_class_name,
            value,
            str(exc),
        )
        raise ValueError(
            f"Cannot coerce {value!r} to {field_class_name} for field {field_name}: {exc}"
        ) from exc

    if field_class_name in ("FileField", "ImageField"):
        # File fields pass through UploadFile objects unchanged
        # The model's pre_save hook will handle file persistence
        # Empty string means clear the file (set to null)
        if value == "":
            return None
        # If it's a string path (existing file), pass through as-is
        return value

    return value
