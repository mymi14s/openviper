"""ORM field definitions for OpenViper models."""

from __future__ import annotations

import datetime
import json
import os
import uuid
from decimal import Decimal
from typing import Any

from openviper.conf import settings
from openviper.utils import timezone


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

    @property
    def column_name(self) -> str:
        return self.db_column or self.name

    def to_python(self, value: Any) -> Any:
        return value

    def to_db(self, value: Any) -> Any:
        return value

    def validate(self, value: Any) -> None:
        if not self.null and value is None:
            raise ValueError(f"Field '{self.name}' cannot be null.")
        if self.choices and value is not None:
            # Rebuild the set if choices was assigned post-construction.
            if not self._choices_set:
                self._choices_set = frozenset(c[0] for c in self.choices)
            if value not in self._choices_set:
                allowed = [c[0] for c in self.choices]
                raise ValueError(f"Field '{self.name}' value {value!r} not in choices {allowed!r}.")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class AutoField(Field):
    """Auto-incrementing integer primary key (added automatically)."""

    _column_type = "INTEGER"

    def __init__(self) -> None:
        super().__init__(primary_key=True, auto_increment=True)

    def to_python(self, value: Any) -> int | None:
        return int(value) if value is not None else None


class IntegerField(Field):
    """Integer column."""

    _column_type = "INTEGER"

    def to_python(self, value: Any) -> int | None:
        return int(value) if value is not None else None

    def to_db(self, value: Any) -> int | None:
        return int(value) if value is not None else None


class BigIntegerField(IntegerField):
    """64-bit integer column."""

    _column_type = "BIGINT"


class FloatField(Field):
    """Floating point column."""

    _column_type = "REAL"

    def to_python(self, value: Any) -> float | None:
        return float(value) if value is not None else None


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
        return Decimal(str(value)) if value is not None else None


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
                import zoneinfo

                return timezone.make_aware(dt, zoneinfo.ZoneInfo("UTC"))
            return dt.astimezone(datetime.UTC)
        else:
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
        else:
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

    def to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value

    def to_db(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)


class ForeignKey(Field):
    """Foreign key relationship.

    Args:
        to: The related model class or string dotted path.
        on_delete: "CASCADE", "PROTECT", "SET_NULL", "SET_DEFAULT".
        related_name: Attribute name on the related model for reverse access.
    """

    _column_type = "INTEGER"

    def __init__(
        self,
        to: type | str,
        on_delete: str = "CASCADE",
        related_name: str | None = None,
        **kwargs: Any,
    ) -> None:
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
                from openviper.utils import import_string

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

        # Try prepending app_label if we belong to a model
        from openviper.db.models import Model

        if hasattr(self, "model_class") and issubclass(self.model_class, Model):
            app_label = getattr(self.model_class, "_app_name", None)
            if app_label:
                full_name = f"{app_label}.{target}"
                if full_name in ModelMeta.registry:
                    return ModelMeta.registry[full_name]

        # Try finding anywhere in registry (brute force search of model names)
        for name, cls in ModelMeta.registry.items():
            if "." in name and name.split(".")[-1] == target:
                return cls
            if name == target:
                return cls

        return None

    @property
    def column_name(self) -> str:
        col = self.db_column or f"{self.name}_id"
        return col


class OneToOneField(ForeignKey):
    """One-to-one relationship (unique FK)."""

    def __init__(self, to: type | str, **kwargs: Any) -> None:
        kwargs["unique"] = True
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

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 254)
        super().__init__(**kwargs)

    def validate(self, value: Any) -> None:
        super().validate(value)
        if value and "@" not in value:
            raise ValueError(f"Field '{self.name}': invalid email address '{value}'.")


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
