"""Field type mapping for admin panel.

Maps OpenViper model fields to frontend component types and configurations
for dynamic form rendering.
"""

from __future__ import annotations

import functools
import importlib
import json
import logging
import typing as t
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

try:
    from openviper.contrib.fields.countries.cache import get_country_choices as country_choices_fn
except ImportError:
    country_choices_fn: t.Callable | None = None

if TYPE_CHECKING:
    from openviper.db.fields import Field

logger = logging.getLogger(__name__)

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
    "CountryField": "country",
    "PointField": "point",
}


def get_field_component_type(field: Field) -> str:
    """Get the Vue component type for a field.

    Args:
        field: The model field instance.

    Returns:
        The component type string (e.g., 'text', 'number', 'select').
    """
    if getattr(field, "choices", None):
        return "select"

    field_class_name = field.__class__.__name__
    return FIELD_COMPONENT_MAP.get(field_class_name, "text")


def get_filter_choices(field: Field) -> list[dict[str, str]]:
    """Return filter choices for a field, including lazy-loaded CountryField data."""
    if field.__class__.__name__ == "CountryField" and country_choices_fn is not None:
        extra = getattr(field, "extra_countries", ())
        return [{"value": code, "label": name} for code, name in country_choices_fn(extra)]
    if hasattr(field, "choices") and field.choices:
        return [{"value": c[0], "label": c[1]} for c in field.choices]
    return []


def get_field_widget_config(field: Field) -> dict[str, t.Any]:
    """Get widget configuration for a field.

    Args:
        field: The model field instance.

    Returns:
        Dict of widget configuration options.
    """
    config: dict[str, t.Any] = {}
    field_class_name = field.__class__.__name__

    config["required"] = not getattr(field, "null", True) and not getattr(field, "blank", True)
    config["readonly"] = (
        field.__class__.__name__ == "AutoField"
        or getattr(field, "auto_increment", False)
        or getattr(field, "auto_now", False)
        or getattr(field, "auto_now_add", False)
    )
    config["help_text"] = getattr(field, "help_text", "")

    if hasattr(field, "choices") and field.choices:
        config["choices"] = [{"value": c[0], "label": c[1]} for c in field.choices]
        for choice in config["choices"]:
            if not isinstance(choice["label"], (str, int, float, bool)):
                choice["label"] = str(choice["label"])

    if field_class_name == "PointField":
        config["srid"] = getattr(field, "srid", 4326)

    if field_class_name == "CharField":
        config["max_length"] = getattr(field, "max_length", 255)

    if field_class_name == "PositiveIntegerField":
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

    if field_class_name in ("ForeignKey", "OneToOneField"):
        config["searchable"] = True
        config["filterable"] = True

    if field_class_name == "CountryField" and country_choices_fn is not None:
        extra = getattr(field, "extra_countries", ())
        choices = country_choices_fn(extra)
        config["choices"] = [{"value": code, "label": name} for code, name in choices]
        config["searchable"] = True
        config["country_field"] = True

    if getattr(field, "primary_key", False):
        config["filterable"] = True

    return config


@functools.lru_cache(maxsize=512)
def get_field_schema_cached(
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
    component: str,
    editable: bool,
) -> dict[str, t.Any]:
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
    schema = {
        "name": field_name,
        "type": field_class_name,
        "component": component,
        "column_type": column_type,
        "primary_key": primary_key,
        "null": null,
        "blank": blank,
        "unique": unique,
        "db_index": db_index,
        "default": None if default_str == "__none__" else default_str,
        "editable": editable,
    }

    if related_model_str:
        schema["related_model"] = related_model_str

    return schema


def get_field_schema(field: Field) -> dict[str, t.Any]:
    """Get complete field schema for API response.

    Args:
        field: The model field instance.

    Returns:
        Dict with field type, component, and configuration.
    """
    field_class_name = field.__class__.__name__

    field_name = getattr(field, "name", "")
    column_type = getattr(field, "_column_type", "TEXT")
    primary_key = getattr(field, "primary_key", False)
    null = getattr(field, "null", False)
    blank = getattr(field, "blank", False)
    unique = getattr(field, "unique", False)
    db_index = getattr(field, "db_index", False)

    default = getattr(field, "default", None)
    default_str = "__none__" if default is None else serialize_default(default)

    related_model_str = None
    if field_class_name in ("ForeignKey", "OneToOneField"):
        related_model = getattr(field, "to", None)
        if related_model:
            if isinstance(related_model, str):
                resolved_model = None
                parts = related_model.split(".")
                model_name = parts[-1]

                if len(parts) >= 2:
                    try:
                        module_path = f"{parts[0]}.models"
                        module = importlib.import_module(module_path)
                        resolved_model = getattr(module, model_name, None)
                    except ImportError, AttributeError:
                        logger.debug("Could not import %s.models.%s", parts[0], model_name)

                    if resolved_model is None and len(parts) >= 3:
                        try:
                            module_path = ".".join(parts[:-1])
                            module = importlib.import_module(module_path)
                            resolved_model = getattr(module, model_name, None)
                        except ImportError, AttributeError:
                            logger.debug("Could not import %s.%s", ".".join(parts[:-1]), model_name)
                    app_name = getattr(
                        resolved_model,
                        "_app_name",
                        parts[0] if len(parts) >= 2 else "default",
                    )
                else:
                    app_name = parts[0] if len(parts) >= 2 else "default"

                related_model_str = f"{app_name}/{model_name}"
            else:
                app_name = getattr(related_model, "_app_name", "default")
                model_name = related_model.__name__
                related_model_str = f"{app_name}/{model_name}"

    schema = get_field_schema_cached(
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
        get_field_component_type(field),
        getattr(field, "editable", True),
    )

    schema["config"] = get_field_widget_config(field)

    return schema


def serialize_default(default: t.Any) -> t.Any:
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


def coerce_field_value(field: Field, value: t.Any) -> t.Any:
    """Coerce a value to the appropriate type for a field.

    Args:
        field: The model field instance.
        value: The value to coerce.

    Returns:
        The coerced value.
    """
    field_name = getattr(field, "name", "unknown")
    field_class_name = field.__class__.__name__

    if value == "__callable__":
        is_auto = getattr(field, "auto", False) or getattr(field, "auto_increment", False)
        if is_auto:
            return None
        raise ValueError(f"Field {field_name} received invalid sentinel value '__callable__'")

    if value is None:
        return None

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
            if isinstance(value, str) and value.isdigit():
                return int(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
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
        if value == "":
            return None
        return value

    return value
