"""ORM field definitions for OpenViper models."""

from __future__ import annotations

import asyncio
import datetime
import functools
import json
import math
import os
import re
import uuid
import zoneinfo
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
from pydantic_core import CoreSchema, core_schema

from openviper.conf import settings
from openviper.http.request import UploadFile
from openviper.utils import import_string, timezone

if TYPE_CHECKING:
    from openviper.db.models import Model

_UTC_ZONE = zoneinfo.ZoneInfo("UTC")


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
        self.name: str = ""  # Set by ModelMeta

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
        if not self.null and value is None:
            if getattr(settings, "DEBUG", False):
                raise ValueError(f"Field '{self.name}' cannot be null.")
            raise ValueError("Required field cannot be empty.")
        if self.choices and value is not None:
            # Rebuild the set if choices was assigned post-construction.
            if not self._choices_set:
                self._choices_set = frozenset(c[0] for c in self.choices)
            if value not in self._choices_set:
                if getattr(settings, "DEBUG", False):
                    allowed = [c[0] for c in self.choices]
                    raise ValueError(
                        f"Field '{self.name}' value {value!r} not in choices {allowed!r}."
                    )
                raise ValueError("Invalid value: not one of the allowed choices.")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class AutoField(Field):
    """Auto-incrementing integer primary key (added automatically)."""

    _column_type = "INTEGER"
    # PostgreSQL INTEGER bounds: -2^31 to 2^31-1
    _MIN_VALUE = -2147483648
    _MAX_VALUE = 2147483647

    def __init__(self) -> None:
        super().__init__(primary_key=True, auto_increment=True)

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if not (
            self._MIN_VALUE <= int_val <= self._MAX_VALUE
        ):  # pylint: disable=superfluous-parens
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val


class IntegerField(Field):
    """Integer column."""

    _column_type = "INTEGER"
    # PostgreSQL INTEGER bounds: -2^31 to 2^31-1
    _MIN_VALUE = -2147483648
    _MAX_VALUE = 2147483647

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if not (
            self._MIN_VALUE <= int_val <= self._MAX_VALUE
        ):  # pylint: disable=superfluous-parens
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val

    def to_db(self, value: Any) -> int | None:
        if value is None:
            return None
        int_val = int(value)
        if not (
            self._MIN_VALUE <= int_val <= self._MAX_VALUE
        ):  # pylint: disable=superfluous-parens
            raise ValueError(
                f"Field '{self.name}': integer value {int_val} exceeds "
                f"database bounds [{self._MIN_VALUE}, {self._MAX_VALUE}]"
            )
        return int_val


class BigIntegerField(IntegerField):
    """64-bit integer column."""

    _column_type = "BIGINT"
    # PostgreSQL BIGINT bounds: -2^63 to 2^63-1
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

        # Count digits - get tuple components: (sign, digits, exponent)
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
            if getattr(settings, "DEBUG", False):
                raise ValueError(f"Field '{self.name}' value exceeds max_length={self.max_length}.")
            raise ValueError(f"Value exceeds maximum length of {self.max_length} characters.")


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

    def to_db(self, value: Any) -> int | None:
        if value is None:
            return None
        return 1 if value else 0


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
                # Assume local time if naive, then convert to UTC
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

    def to_db(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class JSONField(Field):
    """JSON column (stored as TEXT, deserialized automatically)."""

    _column_type = "JSON"

    def __init__(self, *, max_size: int | None = None, **kwargs: Any) -> None:
        """Initialize a JSON field.

        Args:
            max_size: Maximum JSON string size in bytes (default: 1MB)
            **kwargs: Other field arguments
        """
        super().__init__(**kwargs)
        self._max_size = max_size

    @property
    def max_size(self) -> int:
        """Get the maximum JSON size, using setting or default."""
        if self._max_size is not None:
            return self._max_size
        return int(getattr(settings, "MAX_JSON_SIZE", 1024 * 1024))  # 1MB default

    def to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            # Check size before parsing to prevent memory exhaustion
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
        # Serialize only for size validation.
        # We return the Python object because SQLAlchemy's sa.JSON() type
        # handles serialization natively. Stringifying here causes double-encoding.
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
        kwargs.setdefault("db_index", True)
        super().__init__(**kwargs)
        self.to = to
        self.on_delete = on_delete
        self.related_name = related_name

    def resolve_target(self) -> type | None:
        """Resolve the 'to' target to a Model class."""
        if isinstance(self.to, type):
            return self.to

        target = self.to

        # Handle callables directly (e.g. ForeignKey(to=get_user_model))
        if callable(target) and not isinstance(target, type):
            try:
                target = target()
                if isinstance(target, type):
                    return target
            except Exception:
                # If calling fails (e.g. circular dependency), we might have to wait
                pass

        if not isinstance(target, str):
            return None if not isinstance(target, type) else target

        # Dotted path resolution (e.g., 'auth.User' or 'openviper.auth.utils.get_user_model')
        if "." in target:
            try:
                res = import_string(target)
                if isinstance(res, type):
                    return res
                if callable(res):
                    # It could be a getter function path like 'openviper.auth.utils.get_user_model'
                    res = res()
                    if isinstance(res, type):
                        return res
            except (ImportError, AttributeError):
                pass

        # Model registry lookup
        from openviper.db.models import ModelMeta

        # Try original string as key (usually 'app.Model')
        if target in ModelMeta.registry:
            return ModelMeta.registry[target]

        # Compute app_label once if this FK belongs to a model
        from openviper.db.models import Model

        app_label = None
        if hasattr(self, "model_class") and issubclass(self.model_class, Model):
            app_label = getattr(self.model_class, "_app_name", None)

        # Try prepending app_label
        if app_label:
            full_name = f"{app_label}.{target}"
            if full_name in ModelMeta.registry:
                return ModelMeta.registry[full_name]

        # Try finding anywhere in registry via the O(1) name index
        candidates = ModelMeta._name_index.get(target, [])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            # Multiple models share the simple name; prefer one from the same app.
            if app_label:
                for candidate in candidates:
                    if getattr(candidate, "_app_name", None) == app_label:
                        return candidate
            return candidates[0]

        return None

    @property
    def _column_type(self) -> str:  # type: ignore[override]
        """Return the column type matching the target model's primary key field."""
        target = self.resolve_target()
        if target is not None:
            fields: dict[str, Any] = getattr(target, "_fields", {})
            for field in fields.values():
                if field.primary_key:
                    # A nested ForeignKey PK is unusual but handle gracefully
                    if isinstance(field, ForeignKey):
                        return str(field._column_type)
                    return str(field._column_type)
        return "INTEGER"  # default when target is not yet resolvable

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
            # Accessed on class, return descriptor itself
            return self

        # Check if related object is cached (from select_related/prefetch_related)
        if (
            hasattr(obj, "_relation_cache")
            and obj._relation_cache is not None
            and self.name in obj._relation_cache
        ):
            return obj._relation_cache[self.name]

        # Get the FK ID value
        fk_id = obj.__dict__.get(self.column_name, None)

        # Return an awaitable LazyFK proxy that can be awaited to load the object
        return LazyFK(self, obj, fk_id)

    def __set__(self, obj: Any, value: Any) -> None:
        """Allow setting FK field via both ID and model instance.

        Examples:
            post.author_id = 5
            post.author = user_instance  (sets post.author_id = user_instance.id)
        """
        # Unwrap LazyFK proxies so only raw IDs are ever stored in __dict__.
        # This handles the pattern: child.fk_field = parent.other_fk_field
        # where parent.other_fk_field returns a LazyFK descriptor value.
        if isinstance(value, LazyFK):
            value = value.fk_id

        # Check if value is a Model instance
        from openviper.db.models import Model

        if isinstance(value, Model):
            # Extract ID from model instance, set directly in __dict__ to avoid recursion
            obj.__dict__[self.column_name] = value.id
            # Cache the instance for descriptor access (select_related / __str__)
            if hasattr(obj, "_relation_cache"):
                obj._relation_cache[self.name] = value
        else:
            # Set the value directly in __dict__ to avoid descriptor recursion
            obj.__dict__[self.column_name] = value
            # Clear cached relation since raw value changed
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
        # Unwrap any chain of LazyFK proxies (defense-in-depth)
        while isinstance(value, LazyFK):
            value = value.fk_id
            if value is None:
                return None
        # Handle Model instances (e.g., from _relation_cache)
        from openviper.db.models import Model

        if isinstance(value, Model):
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

        # Async import to avoid circular dependency
        from openviper.db.executor import execute_select

        # Get the related model class
        related_model = self.fk_field.resolve_target()
        if related_model is None:
            return None

        # Create a queryset and execute it
        qs = related_model.objects.filter(id=self.fk_id)  # type: ignore[attr-defined]
        results = await execute_select(qs)

        if not results:
            return None

        # Hydrate the object
        self._loaded_obj = related_model._from_row(results[0])  # type: ignore[attr-defined]

        # Cache in the instance
        if hasattr(self.instance, "_relation_cache"):
            self.instance._relation_cache[self.fk_field.name] = self._loaded_obj

        return self._loaded_obj

    def __await__(self) -> Any:
        """Make this object awaitable."""
        return self._load().__await__()

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
            return {"type": "any"}  # Fallback if pydantic-core not installed

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
        # The UNIQUE constraint already creates an implicit index; no extra needed.
        kwargs.setdefault("db_index", False)
        super().__init__(to, **kwargs)


class ManyToManyField(Field):
    """Many-to-many relationship via a junction table.

    This field does not create a column in the model's table.
    """

    _column_type = ""  # No direct column

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


class EmailField(CharField):
    """Email address field (validated on save)."""

    # RFC 5322 simplified email regex
    # Allows local-part@domain format with common characters
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
            # Check for forbidden control characters that could enable header injection
            if any(c in str_value for c in ["\n", "\r", "\0"]):
                raise ValueError(
                    f"Field '{self.name}': email contains forbidden control characters."
                )
            # Validate email pattern
            if not self._EMAIL_PATTERN.match(str_value):
                raise ValueError(f"Field '{self.name}': invalid email address format.")


class SlugField(CharField):
    """URL-safe slug field."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 50)
        super().__init__(**kwargs)


class IPAddressField(CharField):
    """IPv4/IPv6 address field."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 45)
        super().__init__(**kwargs)


class URLField(CharField):
    """URL field."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 2048)
        super().__init__(**kwargs)


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
            return 10 * 1024 * 1024  # 10 MB default

    async def pre_save(self, instance: Model, value: Any) -> None:
        """Handle file upload persistence before saving to database."""
        if value is None or isinstance(value, str):
            return

        content: bytes
        filename: str = ""

        if isinstance(value, UploadFile):
            content = await value.read()
            filename = value.filename
        elif isinstance(value, bytes):
            content = value
            filename = f"upload_{uuid.uuid4().hex[:8]}"
        elif hasattr(value, "read"):
            # File-like object
            if asyncio.iscoroutinefunction(value.read):
                content = await value.read()
            else:
                content = value.read()
            filename = getattr(value, "name", f"upload_{uuid.uuid4().hex[:8]}")
        else:
            return

        # Sanitize filename to prevent path traversal attacks
        # Remove path separators and dangerous characters
        filename = self._sanitize_filename(filename)

        # Construct destination path
        media_root = Path(getattr(settings, "MEDIA_DIR", "./media")).absolute().resolve()
        upload_path = Path(self.upload_to)

        # Ensure directory exists — run in a thread to avoid blocking the event loop
        full_dir = media_root / upload_path
        await asyncio.to_thread(full_dir.mkdir, parents=True, exist_ok=True)

        # Final destination with sanitized filename
        dest_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
        full_path = (full_dir / dest_filename).resolve()

        # ensure resolved path is within media_root
        try:
            full_path.relative_to(media_root)
        except ValueError:
            raise ValueError(
                f"Security error: file path '{dest_filename}' would escape MEDIA_ROOT. "
                f"Path traversal detected."
            ) from None

        # Write file
        async with aiofiles.open(full_path, mode="wb") as f:
            await f.write(content)

        # Update instance with RELATIVE path
        relative_path = str(upload_path / dest_filename)
        setattr(instance, self.name, relative_path)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize a filename to prevent path traversal attacks.

        Removes path separators, null bytes, and other dangerous characters.
        Returns only the base filename, safe for use in file paths.
        """
        # Remove any path components - get only the base filename
        filename = os.path.basename(filename)

        # Remove null bytes and other control characters
        filename = filename.replace("\x00", "").replace("\n", "").replace("\r", "")

        # Remove leading dots (hidden files) and spaces
        filename = filename.lstrip(". ")

        # If filename is now empty or only has an extension, generate a random name
        if not filename or filename.startswith("."):
            filename = f"upload_{uuid.uuid4().hex[:8]}"

        # Limit length to prevent issues
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

        # If it's already a saved path string, use CharField validation
        if isinstance(value, str):
            super().validate(value)
            return

        # Check file size for bytes / file-like objects
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
            # File-like: seek to end, measure, seek back
            pos = value.tell()
            value.seek(0, 2)
            size = value.tell()
            value.seek(pos)
            return int(size)
        return None


class ImageField(FileField):
    """Image upload field.

    Behaves like :class:`FileField` but restricts uploads to image content types.

    Args:
        upload_to: Sub-directory under MEDIA_ROOT for uploaded images.
        max_file_size: Maximum allowed file size in bytes.
        allowed_extensions: Set of permitted file extensions (lowercase, without dot).
    """

    DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
        {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "tiff", "ico"}
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

        # Check extension only for path-style strings
        if isinstance(value, str):
            self._validate_extension(value)
            return

        # For upload objects, check filename extension if available
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
