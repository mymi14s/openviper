"""ORM field definitions for OpenViper models."""

from __future__ import annotations

import asyncio
import datetime
import functools
import html
import inspect
import ipaddress
import json
import logging
import math
import os
import re
import typing as t
import urllib.parse
import uuid
import zoneinfo
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiofiles
from pydantic_core import CoreSchema, core_schema

from openviper.conf import settings
from openviper.db import model_registry
from openviper.db.utils import (
    validate_on_delete,
    validate_sql_expression,
)
from openviper.http.uploads import UploadFile
from openviper.utils import import_string, timezone

if TYPE_CHECKING:
    from openviper.db.models import Model

_UTC_ZONE = zoneinfo.ZoneInfo("UTC")

logger = logging.getLogger(__name__)


def _detect_content_type(content: bytes) -> str | None:
    """Return a MIME type based on magic numbers, or None if unknown."""
    if content.startswith(bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])):
        return "image/png"
    if content.startswith(bytes([0xFF, 0xD8])):
        return "image/jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"BM"):
        return "image/bmp"
    if content.startswith(bytes([0x50, 0x4B, 0x03, 0x04])):
        return "application/zip"
    if content.startswith(b"%PDF"):
        return "application/pdf"
    # Common plain-text markers
    if content[:5].lower() == b"<html" or b"<!doctype html" in content[:128].lower():
        return "text/html"
    return None


_EXT_TO_MIME: dict[str, list[str]] = {
    "png": ["image/png"],
    "jpg": ["image/jpeg"],
    "jpeg": ["image/jpeg"],
    "gif": ["image/gif"],
    "webp": ["image/webp"],
    "bmp": ["image/bmp"],
    "zip": ["application/zip"],
    "pdf": ["application/pdf"],
    "html": ["text/html"],
    "htm": ["text/html"],
}


class Field:
    """Base field descriptor.
    Args:
        primary_key: Mark this field as the table primary key.
        null: Allow NULL values.
        blank: Allow empty strings (validation-only flag).
        unique: Add a UNIQUE constraint.
        db_index: Add a database index.
        default: Default value or callable.
        db_column: Override the column name in the database.
        auto_increment: Auto-increment the column (integer PK).
        choices: List of (db_value, display_value) allowed values.
        help_text: Human-readable description.
    """

    _column_type: str = "TEXT"

    @property
    def column_type(self) -> str:
        """Return the SQL column type for this field."""
        return self._column_type

    @column_type.setter
    def column_type(self, value: str) -> None:
        """Allow subclasses to override the SQL column type."""
        self._column_type = value

    def __init__(
        self,
        primary_key: bool = False,
        null: bool = False,
        blank: bool = False,
        unique: bool = False,
        db_index: bool = False,
        default: Any = None,
        db_column: str | None = None,
        auto_increment: bool = False,
        choices: list[tuple[Any, str]] | None = None,
        help_text: str = "",
        editable: bool = True,
    ) -> None:
        self.primary_key = primary_key
        self.null = null
        self.blank = blank
        self.unique = unique
        self.db_index = db_index
        self.default = default
        self.db_column = db_column
        self.auto_increment = auto_increment
        self.choices = choices or []
        self._choices_set: frozenset[Any] = frozenset(c[0] for c in self.choices)
        self.help_text = help_text
        self.editable = editable
        self.name: str = ""

    @functools.cached_property
    def column_name(self) -> str:
        return self.db_column or self.name

    def to_python(self, value: Any) -> Any:
        return value

    def to_db(self, value: Any) -> Any:
        return value

    async def pre_save(self, instance: Model, value: Any) -> None:
        """Hook called by the executor before saving the model instance.

        Subclasses can override this to perform side effects (e.g. file writing)
        and potentially modify the instance's state before the DB write.
        """
        pass

    def validate(self, value: Any) -> None:
        production_style_errors = not getattr(settings, "DEBUG", False) and getattr(
            settings, "TESTING", False
        )
        if not self.null and value is None:
            if production_style_errors:
                raise ValueError("Required field cannot be empty.")
            raise ValueError(f"Field '{self.name}' cannot be null.")
        if self.choices and value is not None:
            # Rebuild lazily because choices may be mutated after __init__.
            if not self._choices_set:
                self._choices_set = frozenset(c[0] for c in self.choices)
            if value not in self._choices_set:
                if production_style_errors:
                    raise ValueError("Invalid value: not one of the allowed choices.")
                allowed = [c[0] for c in self.choices]
                raise ValueError(f"Field '{self.name}' value {value!r} not in choices {allowed!r}.")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class AutoField(Field):
    """Auto-incrementing integer primary key (added automatically)."""

    _column_type = "INTEGER"
    # PostgreSQL INTEGER column range - values outside cause DB errors.
    _MIN_VALUE = -2147483648
    _MAX_VALUE = 2147483647

    def __init__(self) -> None:
        super().__init__(primary_key=True, auto_increment=True)

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if int_val < self._MIN_VALUE or int_val > self._MAX_VALUE:
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val


class IntegerField(Field):
    """Integer column."""

    _column_type = "INTEGER"
    # PostgreSQL INTEGER column range - values outside cause DB errors.
    _MIN_VALUE = -2147483648
    _MAX_VALUE = 2147483647

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if int_val < self._MIN_VALUE or int_val > self._MAX_VALUE:
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val

    def to_db(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if int_val < self._MIN_VALUE or int_val > self._MAX_VALUE:
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val


class BigIntegerField(IntegerField):
    """64-bit integer column."""

    _column_type = "BIGINT"
    # PostgreSQL BIGINT column range - values outside cause DB errors.
    _MIN_VALUE = -9223372036854775808
    _MAX_VALUE = 9223372036854775807


class FloatField(Field):
    """Floating point column."""

    _column_type = "REAL"

    def __init__(
        self,
        *,
        allow_inf: bool = False,
        allow_nan: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize a Float field.

        Args:
            allow_inf: Whether to allow infinite values (default: False)
            allow_nan: Whether to allow NaN values (default: False)
            **kwargs: Other field arguments
        """
        super().__init__(**kwargs)
        self.allow_inf = allow_inf
        self.allow_nan = allow_nan

    def to_python(self, value: Any) -> float | None:
        if value is None:
            return None

        float_val = float(value)

        if not self.allow_inf and math.isinf(float_val):
            raise ValueError(f"Field '{self.name}': infinite values are not allowed")

        if not self.allow_nan and math.isnan(float_val):
            raise ValueError(f"Field '{self.name}': NaN values are not allowed")

        return float_val


class DecimalField(Field):
    """Fixed-precision decimal column.

    Args:
        max_digits: Total number of digits.
        decimal_places: Digits after the decimal point.
    """

    _column_type = "NUMERIC"

    def __init__(self, max_digits: int = 10, decimal_places: int = 2, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.max_digits = max_digits
        self.decimal_places = decimal_places

    def to_python(self, value: Any) -> Decimal | None:
        if value is None:
            return None

        dec = Decimal(str(value))

        _sign, digits, exponent = dec.as_tuple()
        total_digits = len(digits)
        decimal_places_count = -exponent if isinstance(exponent, int) and exponent < 0 else 0

        if total_digits > self.max_digits:
            raise ValueError(
                f"Field '{self.name}': value has {total_digits} digits, "
                f"exceeds max_digits={self.max_digits}"
            )

        if decimal_places_count > self.decimal_places:
            raise ValueError(
                f"Field '{self.name}': value has {decimal_places_count} decimal places, "
                f"exceeds decimal_places={self.decimal_places}"
            )

        return dec


class CharField(Field):
    """Variable-length string column.

    Args:
        max_length: Maximum number of characters (enforced in validation).
    """

    _column_type = "VARCHAR"

    def __init__(self, max_length: int = 255, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.max_length = max_length

    def to_python(self, value: Any) -> str | None:
        return str(value) if value is not None else None

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and len(str(value)) > self.max_length:
            if not getattr(settings, "DEBUG", False) and getattr(settings, "TESTING", False):
                raise ValueError(f"Value exceeds maximum length of {self.max_length} characters.")
            raise ValueError(f"Field '{self.name}' value exceeds max_length={self.max_length}.")


class TextField(Field):
    """Unbounded text column."""

    _column_type = "TEXT"

    def to_python(self, value: Any) -> str | None:
        return str(value) if value is not None else None


class BooleanField(Field):
    """Boolean column."""

    _column_type = "BOOLEAN"

    def to_python(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")

    def to_db(self, value: Any) -> bool | None:
        if value is None:
            return None
        return bool(value)


class DateTimeField(Field):
    """Datetime column with optional auto_now / auto_now_add helpers.

    Args:
        auto_now: Update to current UTC time on every save().
        auto_now_add: Set current UTC time only on INSERT.
    """

    _column_type = "DATETIME"

    def __init__(self, auto_now: bool = False, auto_now_add: bool = False, **kwargs: Any) -> None:
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add

    def to_python(self, value: Any) -> datetime.datetime | None:
        if value is None:
            return None

        dt = value
        if not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.fromisoformat(str(value))

        if settings.USE_TZ:
            if timezone.is_naive(dt):
                return timezone.make_aware(dt, _UTC_ZONE)
            return dt.astimezone(datetime.UTC)
        if timezone.is_aware(dt):
            return timezone.make_naive(dt, timezone.get_current_timezone())
        return dt

    def to_db(self, value: Any) -> datetime.datetime | None:
        if value is None:
            return None

        dt = value
        if not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.fromisoformat(str(value))

        if settings.USE_TZ:
            if timezone.is_naive(dt):
                # Naive datetimes are ambiguous; treat as local before UTC conversion.
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.astimezone(datetime.UTC)
        if timezone.is_aware(dt):
            return timezone.make_naive(dt, timezone.get_current_timezone())
        return dt


class DateField(Field):
    """Date-only column."""

    _column_type = "DATE"

    def to_python(self, value: Any) -> datetime.date | None:
        if value is None:
            return None
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(str(value))


class TimeField(Field):
    """Time-only column."""

    _column_type = "TIME"

    def to_python(self, value: Any) -> datetime.time | None:
        if value is None:
            return None
        if isinstance(value, datetime.time):
            return value
        return datetime.time.fromisoformat(str(value))


class BinaryField(Field):
    """Large binary column (BYTEA in Postgres, BLOB in others)."""

    _column_type = "BINARY"

    def to_python(self, value: Any) -> bytes | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode()
        return bytes(value)

    def to_db(self, value: Any) -> bytes | None:
        return self.to_python(value)


class UUIDField(Field):
    """UUID column (stored as text)."""

    _column_type = "UUID"

    def __init__(self, auto: bool = False, **kwargs: Any) -> None:
        if auto:
            kwargs.setdefault("default", uuid.uuid4)
        super().__init__(**kwargs)
        self.auto = auto

    def to_python(self, value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))

    def to_db(self, value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# Hard ceiling prevents memory exhaustion from misconfigured
# MAX_JSON_SIZE settings. 50 MB is a reasonable upper bound for any
# JSON payload in a web application.
_HARD_MAX_JSON_SIZE: int = 50 * 1024 * 1024


class JSONField(Field):
    """JSON column (stored as TEXT, deserialized automatically)."""

    _column_type = "JSON"

    def __init__(self, *, max_size: int | None = None, **kwargs: Any) -> None:
        """Initialize a JSON field.

        Args:
            max_size: Maximum JSON string size in bytes (default: 1MB).
                      Cannot exceed 50 MB (hard ceiling for safety).
            **kwargs: Other field arguments
        """
        super().__init__(**kwargs)
        self._max_size = max_size

    @property
    def max_size(self) -> int:
        """Get the maximum JSON size, using setting or default.

        Enforces a hard ceiling of 50 MB to prevent memory exhaustion
        from misconfigured MAX_JSON_SIZE settings.
        """
        if self._max_size is not None:
            return min(self._max_size, _HARD_MAX_JSON_SIZE)
        configured = int(getattr(settings, "MAX_JSON_SIZE", 1024 * 1024))
        return min(configured, _HARD_MAX_JSON_SIZE)

    def to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            # Validate size before json.loads to prevent memory exhaustion.
            if len(value) > self.max_size:
                raise ValueError(
                    f"Field '{self.name}': JSON value size {len(value)} bytes "
                    f"exceeds maximum {self.max_size} bytes"
                )
            return json.loads(value)
        return value

    def to_db(self, value: Any) -> Any:
        if value is None:
            return None
        # Serialize only to measure size; return the Python object because
        # SQLAlchemy's sa.JSON() handles serialization natively and stringifying
        # here would cause double-encoding.
        json_str = json.dumps(value)
        if len(json_str) > self.max_size:
            raise ValueError(
                f"Field '{self.name}': JSON value size {len(json_str)} bytes "
                f"exceeds maximum {self.max_size} bytes"
            )
        return value


class ForeignKey(Field):
    """Foreign key relationship.

    Args:
        to: The related model class or string dotted path.
        on_delete: "CASCADE", "PROTECT", "SET_NULL", "SET_DEFAULT".
        related_name: Attribute name on the related model for reverse access.
    """

    def __init__(
        self,
        to: type | str,
        on_delete: str = "CASCADE",
        related_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        validated_on_delete = validate_on_delete(
            on_delete,
            f"ForeignKey.on_delete for field '{kwargs.get('name', 'unknown')}'",
        )
        kwargs.setdefault("db_index", True)
        super().__init__(**kwargs)
        self.to = to
        self.on_delete = validated_on_delete
        self.related_name = related_name

    def resolve_target(self) -> type | None:
        """Resolve the 'to' target to a Model class."""
        if isinstance(self.to, type):
            return self.to

        target = self.to

        # Support callable targets like ForeignKey(to=get_user_model) for
        # lazy model resolution.
        if callable(target) and not isinstance(target, type):
            try:
                target = target()
                if isinstance(target, type):
                    return target
            except Exception:
                logger.debug("FK callable resolution failed for %s", target, exc_info=True)

        if not isinstance(target, str):
            return None if not isinstance(target, type) else target

        # Dotted paths allow string-based lazy references across modules.
        if "." in target:
            try:
                res = import_string(target)
                if isinstance(res, type):
                    return res
                if callable(res):
                    # The resolved import may be a getter function rather than
                    # a model class directly.
                    resolved = res()
                    if isinstance(resolved, type):
                        return resolved
            except ImportError, AttributeError:
                pass

        # Use the live ModelMeta reference so test fixtures that replace
        # ModelMeta.registry are transparently followed.
        model_meta = model_registry.model_meta_cls
        registry = model_meta.registry if model_meta is not None else model_registry.registry
        name_index = model_meta.name_index if model_meta is not None else model_registry.name_index

        # Most FK strings are 'app.Model' format, a direct registry hit.
        if target in registry:
            return cast("type | None", registry[target])

        # app_label enables disambiguation when multiple models share a name.
        app_label = None
        if hasattr(self, "model_class") and hasattr(self.model_class, "_fields"):
            app_label = getattr(self.model_class, "_app_name", None)

        # Prepending app_label resolves ambiguous bare model names.
        if app_label:
            full_name = f"{app_label}.{target}"
            if full_name in registry:
                return cast("type | None", registry[full_name])

        # The name index provides O(1) lookup when only the model name is known.
        candidates = name_index.get(target, [])
        if len(candidates) == 1:
            return cast("type | None", candidates[0])
        if len(candidates) > 1:
            # Disambiguate by preferring the model from the same application.
            if app_label:
                for candidate in candidates:
                    if getattr(candidate, "_app_name", None) == app_label:
                        return cast("type | None", candidate)
            return cast("type | None", candidates[0])

        return None

    @property
    def _column_type(self) -> str:
        """Return the column type matching the target model's primary key field."""
        target = self.resolve_target()
        if target is not None:
            for field in target._fields.values():
                if field.primary_key:
                    # A nested FK PK is unusual but must not crash resolution.
                    if isinstance(field, ForeignKey):
                        return str(field._column_type)
                    return str(field._column_type)
        return "INTEGER"

    @_column_type.setter
    def _column_type(self, value: object) -> None:
        # ForeignKey column type is derived from the target PK; ignore writes.
        _ = value

    @functools.cached_property
    def column_name(self) -> str:
        col = self.db_column or f"{self.name}_id"
        return col

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        """Descriptor for accessing related model instances.

        Returns:
            - The FK field descriptor if accessed on class (obj is None)
            - The cached related instance if available (from select_related/prefetch)
            - An awaitable LazyFK proxy if not cached (user can await to load)
        """
        if obj is None:
            return self

        # Use prefetch cache to avoid a redundant DB round-trip.
        if (
            hasattr(obj, "_relation_cache")
            and obj._relation_cache is not None
            and self.name in obj._relation_cache
        ):
            return obj._relation_cache[self.name]

        fk_id = obj.__dict__.get(self.column_name, None)

        return LazyFK(self, obj, fk_id)

    def __set__(self, obj: Any, value: Any) -> None:
        """Allow setting FK field via both ID and model instance.

        Examples:
            post.author_id = 5
            post.author = user_instance  (sets post.author_id = user_instance.id)
        """
        # Unwrap LazyFK proxies so only raw IDs are stored in __dict__,
        # handling the pattern where parent.other_fk_field returns a LazyFK.
        if isinstance(value, LazyFK):
            value = value.fk_id

        if hasattr(value, "_fields") and hasattr(value, "pk"):
            # Write directly to __dict__ to bypass this descriptor and avoid
            # infinite recursion.
            obj.__dict__[self.column_name] = value.id
            # Cache the resolved instance so subsequent descriptor reads
            # skip a DB query.
            if hasattr(obj, "set_related"):
                obj.set_related(self.name, value)
        else:
            # Write directly to __dict__ to bypass this descriptor and avoid
            # infinite recursion.
            obj.__dict__[self.column_name] = value
            # Invalidate the relation cache because the FK ID changed.
            if (
                hasattr(obj, "_relation_cache")
                and obj._relation_cache is not None
                and self.name in obj._relation_cache
            ):
                del obj._relation_cache[self.name]

    def to_db(self, value: Any) -> Any:
        """Convert a FK value to its database representation (raw ID)."""
        if value is None:
            return None
        # Defense-in-depth - unwrap any chain of LazyFK proxies before
        # DB serialization.
        while isinstance(value, LazyFK):
            value = value.fk_id
            if value is None:
                return None
        if hasattr(value, "_fields") and hasattr(value, "pk"):
            return value.pk
        return value


class LazyFK:
    """Awaitable proxy for lazy-loaded FK relationships.

    Allows accessing x.author and then awaiting it to load the related object:
        author_proxy = post.author
        author = await author_proxy
        print(author.username)

    Also supports transparent comparison, hashing, and string conversion
    so that code using raw FK ID values continues to work.
    """

    def __init__(self, fk_field: ForeignKey, instance: Any, fk_id: int | None):
        self.fk_field = fk_field
        self.instance = instance
        self.fk_id = fk_id
        self._loaded_obj: Any = None

    async def _load(self) -> Any:
        """Load the related object from database."""
        if self._loaded_obj is not None:
            return self._loaded_obj

        if self.fk_id is None:
            return None

        related_model = self.fk_field.resolve_target()
        if related_model is None:
            return None

        results = await related_model.objects.filter(id=self.fk_id).all()

        if not results:
            return None

        self._loaded_obj = results[0]

        if hasattr(self.instance, "set_related"):
            self.instance.set_related(self.fk_field.name, self._loaded_obj)

        return self._loaded_obj

    def __await__(self) -> Any:
        """Make this object awaitable."""
        return (yield from self._load().__await__())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LazyFK):
            return self.fk_id == other.fk_id
        return self.fk_id == other

    def __hash__(self) -> int:
        return hash(self.fk_id)

    def __int__(self) -> int:
        return int(self.fk_id) if self.fk_id is not None else 0

    def __index__(self) -> int:
        return self.__int__()

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: Any) -> CoreSchema:
        if core_schema is None:
            return {"type": "any"}

        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.any_schema(),
        )

    @staticmethod
    def _validate(value: Any) -> Any:
        if isinstance(value, LazyFK):
            return value.fk_id
        return value

    def __bool__(self) -> bool:
        return self.fk_id is not None

    def __str__(self) -> str:
        if self._loaded_obj is not None:
            return str(self._loaded_obj)
        if self.fk_id is not None:
            return str(self.fk_id)
        return ""

    def __repr__(self) -> str:
        if self._loaded_obj is not None:
            return repr(self._loaded_obj)
        return f"<LazyFK {self.fk_field.name} id={self.fk_id}>"


class OneToOneField(ForeignKey):
    """One-to-one relationship (unique FK)."""

    def __init__(self, to: type | str, **kwargs: Any) -> None:
        kwargs["unique"] = True
        # UNIQUE implies an index, so a separate db_index is redundant.
        kwargs.setdefault("db_index", False)
        super().__init__(to, **kwargs)


class ManyToManyManager:
    """Manager for ManyToMany relationships providing add, remove, all, clear methods."""

    def __init__(
        self,
        instance: Any,
        field: ManyToManyField,
        through_model: type,
        target_model: type,
        source_field_name: str,
        target_field_name: str,
    ) -> None:
        self.instance = instance
        self.field = field
        self.through_model = through_model
        self.target_model = target_model
        self.source_field_name = source_field_name
        self.target_field_name = target_field_name

    async def all(self) -> list[Any]:
        """Get all related objects."""
        # Use prefetch cache to avoid a redundant DB round-trip.
        cached = self.instance._get_related(self.field.name)
        if cached is not None:
            return cast("list[Any]", cached)

        if not self.instance.pk:
            return []

        filter_kwargs = {self.source_field_name: self.instance.pk}
        through_objects = (
            await self.through_model.objects.filter(**filter_kwargs)
            .select_related(self.target_field_name)
            .all()
        )

        results = []
        ids_to_fetch = []
        for through_obj in through_objects:
            target_obj = getattr(through_obj, self.target_field_name, None)
            if hasattr(target_obj, "pk"):
                results.append(target_obj)
            elif isinstance(target_obj, int):
                ids_to_fetch.append(target_obj)

        if ids_to_fetch:
            fetched = await self.target_model.objects.filter(id__in=ids_to_fetch).all()
            results.extend(fetched)

        return results

    async def add(self, *objects: Any) -> None:
        """Add one or more objects to the relationship."""
        if not self.instance.pk:
            raise ValueError("Cannot add to ManyToMany before saving the instance")

        target_pks = []
        for obj in objects:
            pk = obj.pk if hasattr(obj, "pk") else obj
            if not pk:
                raise ValueError("Cannot add unsaved object to ManyToMany")
            target_pks.append(pk)

        if not target_pks:
            return

        # Deduplicate in one query to avoid redundant INSERT errors.
        existing_pks = set(
            await self.through_model.objects.filter(
                **{
                    self.source_field_name: self.instance.pk,
                    f"{self.target_field_name}__in": target_pks,
                }
            ).values_list(self.target_field_name, flat=True)
        )

        to_add = [pk for pk in target_pks if pk not in existing_pks]
        if to_add:
            new_rows = [
                self.through_model(
                    **{
                        self.source_field_name: self.instance.pk,
                        self.target_field_name: pk,
                    }
                )
                for pk in to_add
            ]
            await self.through_model.objects.bulk_create(new_rows, ignore_permissions=True)

    async def remove(self, *objects: Any) -> None:
        """Remove one or more objects from the relationship."""
        if not self.instance.pk:
            return

        target_pks = [obj.pk if hasattr(obj, "pk") else obj for obj in objects]
        if not target_pks:
            return

        await self.through_model.objects.filter(
            **{
                self.source_field_name: self.instance.pk,
                f"{self.target_field_name}__in": target_pks,
            }
        ).delete()

    async def clear(self) -> None:
        """Remove all objects from the relationship."""
        if not self.instance.pk:
            return

        await self.through_model.objects.filter(
            **{self.source_field_name: self.instance.pk}
        ).delete()

    async def count(self) -> int:
        """Get the count of related objects."""
        if not self.instance.pk:
            return 0

        filter_kwargs = {self.source_field_name: self.instance.pk}
        return int(await self.through_model.objects.filter(**filter_kwargs).count())

    async def set(self, objects: list[Any]) -> None:
        """Replace the full set of related objects with *objects*.

        Performs a minimal diff: removes only the entries no longer wanted and
        adds only entries that do not already exist, avoiding redundant deletes
        and inserts.
        """
        if not self.instance.pk:
            raise ValueError("Cannot set ManyToMany before saving the instance")

        target_pks = []
        for obj in objects:
            pk = obj.pk if hasattr(obj, "pk") else obj
            if not pk:
                raise ValueError("Cannot set unsaved object in ManyToMany")
            target_pks.append(pk)

        current_pks = set(
            await self.through_model.objects.filter(
                **{self.source_field_name: self.instance.pk}
            ).values_list(self.target_field_name, flat=True)
        )
        wanted_pks = set(target_pks)
        to_remove = current_pks - wanted_pks
        to_add = wanted_pks - current_pks

        if to_remove:
            await self.through_model.objects.filter(
                **{
                    self.source_field_name: self.instance.pk,
                    f"{self.target_field_name}__in": list(to_remove),
                }
            ).delete()

        if to_add:
            new_rows = [
                self.through_model(
                    **{
                        self.source_field_name: self.instance.pk,
                        self.target_field_name: pk,
                    }
                )
                for pk in to_add
            ]
            await self.through_model.objects.bulk_create(new_rows, ignore_permissions=True)


class ReverseRelationDescriptor:
    """Descriptor for reverse FK access via ``related_name``.

    Set on the *target* model by ``ModelMeta`` when a ``ForeignKey`` with a
    ``related_name`` is encountered.  Accessing the attribute on a model
    instance returns a pre-filtered ``QuerySet`` over the source model.

    Example::

        class SampleModel(Model):
            user = ForeignKey(User, on_delete="CASCADE", related_name="otps")

        u = await User.objects.get(id=1)
        active_otps = await u.otps.filter(is_active=True).all()
    """

    def __init__(self, source_model: type, fk_field_name: str) -> None:
        self._source_model = source_model
        self._fk_field_name = fk_field_name

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        if obj is None:
            return self
        queryset_cls = model_registry.queryset_cls
        if queryset_cls is None:
            raise RuntimeError("QuerySet class is not registered.")
        return cast("type", queryset_cls)(self._source_model).filter(
            **{self._fk_field_name: obj.pk}
        )


class ManyToManyDescriptor:
    """Descriptor that returns a ManyToManyManager when accessed from an instance."""

    def __init__(self, field: ManyToManyField) -> None:
        self.field = field

    def __get__(
        self, instance: Any, owner: type | None = None
    ) -> ManyToManyManager | ManyToManyDescriptor:
        if instance is None:
            return self

        model_meta = model_registry.model_meta_cls
        live_registry = model_meta.registry if model_meta is not None else model_registry.registry

        if isinstance(self.field.to, str):
            target_model = live_registry.get(self.field.to)
            if not target_model:
                raise ValueError(f"Cannot resolve target model '{self.field.to}'")
        else:
            target_model = self.field.to

        if self.field.through:
            if isinstance(self.field.through, str):
                through_model = live_registry.get(self.field.through)
                if not through_model:
                    raise ValueError(f"Cannot resolve through model '{self.field.through}'")
            else:
                through_model = self.field.through
        else:
            raise ValueError(
                f"ManyToManyField '{self.field.name}': through model could not be resolved."
            )

        target_model = cast("type", target_model)
        through_model = cast("type", through_model)

        # Auto-created through models expose field names directly, avoiding
        # expensive FK introspection.
        if hasattr(self.field, "_auto_source_field") and hasattr(self.field, "_auto_target_field"):
            source_field_name: str | None = self.field._auto_source_field
            target_field_name: str | None = self.field._auto_target_field
        else:
            # Explicit through models lack stored field names, so match FK
            # targets by model name heuristically.
            source_model_name = instance.__class__.__name__.lower()
            target_model_name = target_model.__name__.lower()
            through_fields = through_model._fields
            source_field_name = None
            target_field_name = None

            for fname, fobj in through_fields.items():
                if isinstance(fobj, ForeignKey):
                    fk_to = fobj.to
                    if isinstance(fk_to, str):
                        fk_model_name = fk_to.rsplit(".", 1)[-1]
                        if (
                            source_model_name == fk_model_name.lower()
                            or instance.__class__.__name__ == fk_model_name
                        ):
                            source_field_name = fname
                        elif (
                            target_model_name == fk_model_name.lower()
                            or target_model.__name__ == fk_model_name
                        ):
                            target_field_name = fname
                    else:
                        if (
                            fk_to is instance.__class__
                            or fk_to.__name__ == instance.__class__.__name__
                        ):
                            source_field_name = fname
                        elif fk_to is target_model or fk_to.__name__ == target_model.__name__:
                            target_field_name = fname

        if not source_field_name or not target_field_name:
            raise ValueError(
                f"Cannot determine field names in through model '{through_model.__name__}'. "
                f"Found source={source_field_name}, target={target_field_name}"
            )

        return ManyToManyManager(
            instance=instance,
            field=self.field,
            through_model=through_model,
            target_model=target_model,
            source_field_name=source_field_name,
            target_field_name=target_field_name,
        )

    def __set__(self, instance: Any, value: Any) -> None:
        # None is valid during model construction before relations are set.
        if value is None:
            return
        raise AttributeError("Cannot set ManyToMany field directly, use add()/remove() methods")


class ManyToManyField(Field):
    """Many-to-many relationship via a junction table.

    This field does not create a column in the model's table.

    Args:
        to: Target model class or string reference
        through: Junction table model class or string reference (required)
        related_name: Name for reverse relation (optional)

    Example:
        class User(Model):
            roles = ManyToManyField(to="Role", through="UserRole")

        class Role(Model):
            permissions = ManyToManyField(to="Permission", through="RolePermission")

        # Usage:
        await user.roles.add(role)
        roles = await user.roles.all()
        await user.roles.remove(role)
    """

    _column_type = ""

    def __init__(
        self,
        to: type | str,
        through: type | str | None = None,
        related_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.to = to
        self.through = through
        self.related_name = related_name

    def contribute_to_class(self, model_class: type, name: str) -> None:
        """Called by metaclass to set up the descriptor."""
        self.name = name
        if self.through is None:
            self.through = self._create_auto_through_model(model_class, name)
        setattr(model_class, name, ManyToManyDescriptor(self))

    def _create_auto_through_model(self, source_model: type, field_name: str) -> type:
        """Auto-generate a junction Model when 'through' is not specified."""
        source_name = source_model.__name__
        target = self.to
        if isinstance(target, type):
            target_name = target.__name__
        else:
            target_name = str(target).rsplit(".", 1)[-1]

        auto_model_name = f"{source_name}{target_name}"
        source_fk_name = source_name.lower()
        target_fk_name = target_name.lower()

        app_name = getattr(source_model, "_app_name", "default")
        model_meta_ref = model_registry.model_meta_cls
        live_reg = (
            model_meta_ref.registry if model_meta_ref is not None else model_registry.registry
        )
        registry_key = f"{app_name}.{auto_model_name}"
        if registry_key in live_reg:
            existing = live_reg[registry_key]
            self._auto_source_field = source_fk_name
            self._auto_target_field = target_fk_name
            return cast("type", existing)

        source_table = getattr(source_model, "_table_name", source_name.lower())
        auto_meta = type("Meta", (), {"table_name": f"{source_table}_{field_name}"})

        if model_registry.model_cls is None or model_registry.model_meta_cls is None:
            raise RuntimeError("Model registry is not initialized.")
        model_base = cast("type", model_registry.model_cls)
        model_meta_cls = cast("type", model_registry.model_meta_cls)
        through_cls = model_meta_cls(
            auto_model_name,
            (model_base,),
            {
                source_fk_name: ForeignKey(source_model, on_delete="CASCADE"),
                target_fk_name: ForeignKey(target, on_delete="CASCADE"),
                "__module__": source_model.__module__,
                "Meta": auto_meta,
            },
        )
        through_cls._is_auto_created = True
        self._auto_source_field = source_fk_name
        self._auto_target_field = target_fk_name
        return cast("type", through_cls)


class EmailField(CharField):
    """Email address field (validated on save)."""

    # RFC 5322 simplified regex balances strict validation with
    # accepting common real-world email formats.
    _EMAIL_PATTERN = re.compile(
        r"^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@"
        r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 254)
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value:
            str_value = str(value)
            # C0 controls and DEL enable header injection and other
            # injection attacks in downstream email processing.
            if any(ord(c) <= 0x1F or ord(c) == 0x7F for c in str_value):
                raise ValueError(
                    f"Field '{self.name}': email contains forbidden control characters."
                )
            if not self._EMAIL_PATTERN.match(str_value):
                raise ValueError(f"Field '{self.name}': invalid email address format.")


class SlugField(CharField):
    """URL-safe slug field with strict character validation."""

    _SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9_-]*[a-zA-Z0-9])?$")

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 50)
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            str_value = str(value)
            if not self._SLUG_PATTERN.match(str_value):
                raise ValueError(
                    f"Field '{self.name}': {str_value!r} is not a valid slug. "
                    f"Only alphanumeric characters, hyphens, and underscores are allowed."
                )


class IPAddressField(CharField):
    """IPv4/IPv6 address field."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 45)
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            try:
                ipaddress.ip_address(str(value))
            except ValueError:
                raise ValueError(
                    f"Field '{self.name}': {value!r} is not a valid IP address."
                ) from None


class URLField(CharField):
    """URL field."""

    _ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 2048)
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None:
            parsed = urllib.parse.urlparse(str(value))
            if parsed.scheme not in self._ALLOWED_SCHEMES or not parsed.netloc:
                raise ValueError(
                    f"Field '{self.name}': {value!r} is not a valid URL. "
                    f"Allowed schemes: {sorted(self._ALLOWED_SCHEMES)}."
                )


class PositiveIntegerField(IntegerField):
    """Integer field that only permits non-negative values."""

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and int(value) < 0:
            raise ValueError(f"Field '{self.name}': value must be >= 0, got {value!r}.")


class FileField(CharField):
    """File upload field.

    Stores the relative file path in the database as a VARCHAR column.
    The actual file is persisted through the storage backend.

    Args:
        upload_to: Sub-directory under MEDIA_ROOT for uploaded files.
        max_file_size: Maximum allowed file size in bytes.
                       ``None`` means use the global ``MAX_FILE_SIZE`` setting.
        max_length: Maximum path string length in the database.
    """

    def __init__(
        self,
        upload_to: str = "uploads/",
        max_file_size: int | None = None,
        max_length: int = 512,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("null", True)
        kwargs.setdefault("blank", True)
        super().__init__(max_length=max_length, **kwargs)
        self.upload_to = upload_to.rstrip("/") + "/"
        self._max_file_size = max_file_size

    @property
    def max_file_size(self) -> int:
        """Return the effective max file size in bytes."""
        if self._max_file_size is not None:
            return self._max_file_size
        try:
            return int(getattr(settings, "MAX_FILE_SIZE", 10 * 1024 * 1024))
        except Exception:
            logger.debug("Invalid MAX_FILE_SIZE setting, using default")
            return 10 * 1024 * 1024

    async def pre_save(self, instance: Model, value: Any) -> None:
        """Handle file upload persistence before saving to database."""
        if value is None or isinstance(value, str):
            return

        content: bytes
        filename: str = ""

        if isinstance(value, UploadFile):
            # Validate size before reading into memory to prevent memory
            # exhaustion from oversized uploads.
            if (
                hasattr(value, "size")
                and value.size is not None
                and value.size > self.max_file_size
            ):
                raise ValueError(
                    f"File size ({value.size} bytes) exceeds maximum "
                    f"allowed size ({self.max_file_size} bytes)."
                )
            content = await value.read()
            filename = value.filename
        elif isinstance(value, bytes):
            content = value
            filename = f"upload_{uuid.uuid4().hex[:8]}"
        elif hasattr(value, "read"):
            if inspect.iscoroutinefunction(value.read):
                content = await value.read()
            else:
                content = value.read()
            filename = getattr(value, "name", f"upload_{uuid.uuid4().hex[:8]}")
        else:
            return

        # Re-check size after reading because UploadFile.size may be absent
        # or inaccurate for some content sources.
        if len(content) > self.max_file_size:
            raise ValueError(
                f"File size ({len(content)} bytes) exceeds maximum "
                f"allowed size ({self.max_file_size} bytes)."
            )

        # Validate actual content against the declared type/extension.
        declared_type = (
            getattr(value, "content_type", None) if isinstance(value, UploadFile) else None
        )
        self._validate_content_type(content, declared_type or "", filename)

        filename = self._sanitize_filename(filename)

        media_root = Path(getattr(settings, "MEDIA_DIR", "./media")).absolute().resolve()
        upload_path = Path(self.upload_to)

        full_dir = media_root / upload_path
        # Filesystem I/O must not block the async event loop.
        await asyncio.to_thread(full_dir.mkdir, parents=True, exist_ok=True)

        dest_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
        # resolve() follows symlinks, so comparing the resolved absolute
        # path against media_root detects path traversal including symlinks that
        # point outside the allowed directory.
        resolved_path = (full_dir / dest_filename).resolve()
        try:
            resolved_path.relative_to(media_root)
        except ValueError:
            raise ValueError(
                f"Security error: file path '{dest_filename}' would escape MEDIA_ROOT. "
                f"Path traversal detected."
            ) from None

        # Symlinks in the upload path enable TOCTOU attacks where an
        # attacker replaces a legitimate file with a symlink between the check
        # and the write. Only the parent directory is checked because the
        # destination file does not yet exist.
        if full_dir.exists() and full_dir.is_symlink():
            raise ValueError(
                f"Security error: symlink detected in upload directory '{full_dir}'. "
                f"Symlinks are not permitted in file upload paths."
            )

        async with aiofiles.open(resolved_path, mode="wb") as f:
            await f.write(content)

        relative_path = str(upload_path / dest_filename)
        setattr(instance, self.name, relative_path)

    def _validate_content_type(self, content: bytes, declared: str, filename: str) -> None:
        """Validate uploaded content structurally via magic numbers.

        Rejects uploads where the declared content type does not match the
        actual file signature.  This prevents attackers from serving
        executable content under a benign MIME type or extension.
        """
        ext = os.path.splitext(filename)[1].lstrip(".").lower()
        detected = _detect_content_type(content)
        if detected is None:
            return
        allowed = {declared.lower()} if declared else set()
        allowed.update(_EXT_TO_MIME.get(ext, []))
        if not allowed or detected in allowed:
            return
        # Some image types are reported with overlapping signatures; permit
        # common image families when the extension also claims an image type.
        if detected.startswith("image/") and any(a.startswith("image/") for a in allowed):
            return
        raise ValueError(
            f"Field '{self.name}': declared content type {declared!r} does not "
            f"match detected file signature {detected!r}."
        )

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize a filename to prevent path traversal attacks.

        Removes path separators, null bytes, control characters, and other
        dangerous characters.  Returns only the base filename, safe for use
        in file paths.  Uses an allowlist approach: only alphanumeric
        characters, hyphens, underscores, dots, and plus signs are preserved.
        """
        # Null bytes and controls before basename can bypass path
        # separator checks (e.g. "dir\x00/evil.txt").
        filename = filename.replace("\x00", "").replace("\n", "").replace("\r", "")
        filename = os.path.basename(filename)
        # Allowlist approach prevents Unicode RTL overrides, unusual
        # whitespace, and other tricks that could confuse path rendering or
        # downstream processing.
        filename = re.sub(r"[^\w\-.+]", "_", filename)
        filename = filename.lstrip(". ")

        if not filename or filename.startswith("."):
            filename = f"upload_{uuid.uuid4().hex[:8]}"

        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[:250] + ext

        return filename

    def validate(self, value: Any) -> None:
        """Validate the value.

        If *value* is a raw bytes/file-like object, check size constraints.
        If *value* is a string path (already saved), run normal CharField validation.
        """
        if value is None:
            if not self.null:
                raise ValueError(f"Field '{self.name}' cannot be null.")
            return

        # Saved path strings have already passed upload validation.
        if isinstance(value, str):
            super().validate(value)
            return

        size = self._get_content_size(value)
        if size is not None and size > self.max_file_size:
            max_mb = self.max_file_size / (1024 * 1024)
            raise ValueError(
                f"Field '{self.name}': file size {size} bytes exceeds "
                f"maximum allowed size of {self.max_file_size} bytes ({max_mb:.1f} MB)."
            )

    @staticmethod
    def _get_content_size(value: Any) -> int | None:
        """Attempt to determine the byte-size of a file value."""
        if isinstance(value, bytes):
            return len(value)
        if hasattr(value, "size"):
            return int(value.size)
        if hasattr(value, "seek") and hasattr(value, "tell") and hasattr(value, "read"):
            pos = value.tell()
            value.seek(0, 2)
            size = value.tell()
            value.seek(pos)
            return int(size)
        return None


class ImageField(FileField):
    """Image upload field.

    Behaves like :class:`FileField` but restricts uploads to image content types.

    Note:
        SVG files are NOT allowed by default due to XSS risks. If you need
        to accept SVG uploads, explicitly set ``allowed_extensions`` and
        ensure you sanitize the content appropriately.

    Args:
        upload_to: Sub-directory under MEDIA_ROOT for uploaded images.
        max_file_size: Maximum allowed file size in bytes.
        allowed_extensions: Set of permitted file extensions (lowercase, without dot).
    """

    # SVG can embed JavaScript, creating XSS vectors; opt-in required.
    DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
        {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "ico"}
    )

    def __init__(
        self,
        upload_to: str = "images/",
        max_file_size: int | None = None,
        allowed_extensions: set[str] | frozenset[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(upload_to=upload_to, max_file_size=max_file_size, **kwargs)
        self.allowed_extensions = (
            frozenset(e.lower() for e in allowed_extensions)
            if allowed_extensions is not None
            else self.DEFAULT_ALLOWED_EXTENSIONS
        )

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is None:
            return

        if isinstance(value, str):
            self._validate_extension(value)
            return

        filename = getattr(value, "filename", None) or getattr(value, "name", None)
        if filename:
            self._validate_extension(filename)

    def _validate_extension(self, filename: str) -> None:

        ext = os.path.splitext(filename)[1].lstrip(".").lower()
        if ext and ext not in self.allowed_extensions:
            raise ValueError(
                f"Field '{self.name}': file extension '.{ext}' is not allowed. "
                f"Allowed extensions: {sorted(self.allowed_extensions)}."
            )


nh3_lib: t.Any

try:
    import nh3 as nh3_lib
except ImportError:
    nh3_lib = None

DEFAULT_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "acronym",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "small",
        "strong",
        "sub",
        "sup",
        "ul",
    }
)

DEFAULT_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title"}),
}

DEFAULT_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})


class HTMLField(TextField):
    """HTML content field with XSS sanitization.

    Stores raw HTML but sanitizes input on assignment using *nh3*
    (preferred) or ``html.escape`` as a safe fallback. Configurable
    allowed tags, attributes, and URL schemes restrict what markup
    survives the cleaning pass.

    Args:
        allowed_tags: Set of HTML tags that survive sanitization.
            Defaults to ``DEFAULT_ALLOWED_TAGS``.
        allowed_attributes: Mapping of tag names to sets of allowed
            attribute names.  Defaults to ``DEFAULT_ALLOWED_ATTRIBUTES``.
        allowed_schemes: URL schemes permitted in ``href`` and ``src``
            attributes.  Defaults to ``DEFAULT_ALLOWED_SCHEMES``.
        strip_comments: Remove HTML comments during sanitization.
    """

    column_type = "TEXT"

    def __init__(
        self,
        allowed_tags: frozenset[str] | None = None,
        allowed_attributes: dict[str, frozenset[str]] | None = None,
        allowed_schemes: frozenset[str] | None = None,
        strip_comments: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.allowed_tags = allowed_tags if allowed_tags is not None else DEFAULT_ALLOWED_TAGS
        self.allowed_attributes = (
            allowed_attributes if allowed_attributes is not None else DEFAULT_ALLOWED_ATTRIBUTES
        )
        self.allowed_schemes = (
            allowed_schemes if allowed_schemes is not None else DEFAULT_ALLOWED_SCHEMES
        )
        self.strip_comments = strip_comments

    def sanitize(self, value: str) -> str:
        """Strip dangerous HTML markup from *value*.

        Uses *nh3* for tag/attribute-level sanitization when available.
        Falls back to full HTML entity escaping via ``html.escape`` when
        *nh3* is not installed, which neutralises all tags and is safe but
        loses formatting.
        """
        if nh3_lib is not None:
            return t.cast(
                "str",
                nh3_lib.clean(
                    value,
                    tags=self.allowed_tags,
                    attributes=self.allowed_attributes,
                    url_schemes=self.allowed_schemes,
                    strip_comments=self.strip_comments,
                ),
            )
        return html.escape(value)

    def to_python(self, value: Any) -> str | None:
        if value is None:
            return None
        return self.sanitize(str(value))

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Field '{self.name}': expected a string, got {type(value).__name__}.")


class SmallIntegerField(IntegerField):
    """16-bit integer column (-32 768 to 32 767).

    Suitable for fields that never exceed the SmallIntegerField range
    and where storage compactness matters.
    """

    _column_type = "SMALLINT"
    _MIN_VALUE = -32768
    _MAX_VALUE = 32767


class BigAutoField(Field):
    """Auto-incrementing 64-bit integer primary key."""

    _column_type = "BIGINT"
    _MIN_VALUE = -9223372036854775808
    _MAX_VALUE = 9223372036854775807

    def __init__(self) -> None:
        super().__init__(primary_key=True, auto_increment=True)

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if not (self._MIN_VALUE <= int_val <= self._MAX_VALUE):
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val


class NullBooleanField(BooleanField):
    """Boolean column that explicitly allows NULL values.

    Equivalent to ``BooleanField(null=True)`` but more explicit about intent.
    Three-state: ``True``, ``False``, or ``None``.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs["null"] = True
        super().__init__(**kwargs)


class DurationField(Field):
    """Duration / timedelta column.

    Stored as a ``BIGINT`` representing total microseconds for maximum
    portability across databases.  Returned as :class:`datetime.timedelta`.
    """

    _column_type = "BIGINT"

    def to_python(self, value: Any) -> datetime.timedelta | None:
        if value is None:
            return None
        if isinstance(value, datetime.timedelta):
            return value
        return datetime.timedelta(microseconds=int(value))

    def to_db(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, datetime.timedelta):
            return int(value.total_seconds() * 1_000_000)
        return int(value)


class GenericIPAddressField(CharField):
    """IPv4 or IPv6 address field with protocol validation.

    Args:
        protocol: ``"both"`` (default), ``"IPv4"``, or ``"IPv6"``.
        unpack_ipv4: If ``True`` and *protocol* is ``"both"``, IPv4-mapped
            IPv6 addresses (e.g. ``::ffff:192.0.2.1``) are unpacked to plain
            IPv4 format before saving.
    """

    _PROTOCOLS: frozenset[str] = frozenset({"both", "IPv4", "IPv6"})

    def __init__(
        self,
        protocol: str = "both",
        unpack_ipv4: bool = False,
        **kwargs: Any,
    ) -> None:
        if protocol not in self._PROTOCOLS:
            raise ValueError(
                f"Invalid protocol {protocol!r}. Must be one of: "
                + ", ".join(sorted(self._PROTOCOLS))
            )
        kwargs.setdefault("max_length", 39)
        super().__init__(**kwargs)
        self.protocol = protocol
        self.unpack_ipv4 = unpack_ipv4

    def _parse_ip(self, value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        """Return a parsed IP object or None if *value* is invalid."""
        try:
            return ipaddress.ip_address(value)
        except ValueError:
            return None

    def to_python(self, value: Any) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        ip = self._parse_ip(raw)
        if ip is None:
            return raw
        if self.unpack_ipv4 and isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ip)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value is None:
            return
        raw = str(value).strip()
        ip = self._parse_ip(raw)
        if ip is None:
            raise ValueError(f"Field '{self.name}': {raw!r} is not a valid IP address.")
        if self.protocol == "IPv4" and not isinstance(ip, ipaddress.IPv4Address):
            raise ValueError(f"Field '{self.name}': {raw!r} is not a valid IPv4 address.")
        if self.protocol == "IPv6" and not isinstance(ip, ipaddress.IPv6Address):
            raise ValueError(f"Field '{self.name}': {raw!r} is not a valid IPv6 address.")


class Constraint:
    """Base class for database constraints declared in ``Meta.constraints``."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class CheckConstraint(Constraint):
    """Database CHECK constraint.

    The *check* string is a raw SQL expression passed directly to the database.
    Use this for simple value-range or cross-column invariants.

    The expression is validated against dangerous SQL patterns (semicolons,
    comments, DDL/DML keywords) to prevent statement injection.

    Example::

        class Price(Model):
            amount = DecimalField(max_digits=10, decimal_places=2)

            class Meta:
                constraints = [
                    CheckConstraint(name="price_positive", check="amount > 0"),
                ]
    """

    __slots__ = ("name", "check")

    def __init__(self, *, name: str, check: str) -> None:
        super().__init__(name)
        validate_sql_expression(check, "check", "CheckConstraint")
        self.check = check

    def __repr__(self) -> str:
        return f"CheckConstraint(name={self.name!r}, check={self.check!r})"


class UniqueConstraint(Constraint):
    """Unique constraint across one or more columns, with optional condition.

    Provides more flexibility than ``Meta.unique_together`` by supporting
    a ``condition`` (partial unique index) and explicit naming.

    The *condition* string is validated against dangerous SQL patterns to
    prevent statement injection.

    Args:
        fields: Column names that must be collectively unique.
        name: Constraint name in the database.
        condition: Optional raw SQL ``WHERE`` clause for a partial unique index.

    Example::

        class Article(Model):
            slug = SlugField()
            published = BooleanField(default=False)

            class Meta:
                constraints = [
                    UniqueConstraint(
                        fields=["slug"],
                        name="unique_published_slug",
                        condition="published = 1",
                    ),
                ]
    """

    __slots__ = ("name", "fields", "condition")

    def __init__(
        self,
        *,
        fields: list[str],
        name: str,
        condition: str | None = None,
    ) -> None:
        super().__init__(name)
        if condition is not None:
            validate_sql_expression(condition, "condition", "UniqueConstraint")
        self.fields = fields
        self.condition = condition

    def __repr__(self) -> str:
        return (
            f"UniqueConstraint(fields={self.fields!r}, name={self.name!r}, "
            f"condition={self.condition!r})"
        )
