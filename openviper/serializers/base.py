"""Pydantic-based serializer/schema base for OpenViper.

Provides ``Serializer`` as a thin convenience layer over ``pydantic.BaseModel``
 full Pydantic v2 power available.

``ModelSerializer`` goes a step further: it introspects a OpenViper ``Model``
class and auto-generates Pydantic fields so you never have to duplicate
your schema definition.

Usage::

    from openviper.serializers import Serializer, ModelSerializer
    from myapp.models import Post

    # Manual serializer
    class PostSerializer(Serializer):
        title: str
        body: str
        tags: list[str] = []

    # Auto-generated from model
    class PostSerializer(ModelSerializer):
        class Meta:
            model = Post
            fields = "__all__"

    # Validate incoming data
    post = PostSerializer.validate({"title": "Hello", "body": "World"})

    # Serialize an ORM model instance
    data = PostSerializer.from_orm(db_post).serialize()

Field Validation::

    from openviper.serializers import Serializer, field_validator

    class UserSerializer(Serializer):
        username: str
        age: int

        @field_validator("username")
        @classmethod
        def validate_username(cls, v: str) -> str:
            if len(v) < 3:
                raise ValueError("Username must be at least 3 characters")
            return v.lower()

        @field_validator("age")
        @classmethod
        def validate_age(cls, v: int) -> int:
            if v < 0 or v > 150:
                raise ValueError("Age must be between 0 and 150")
            return v

Model Validation (cross-field)::

    from openviper.serializers import Serializer, model_validator

    class PasswordChangeSerializer(Serializer):
        password: str
        confirm_password: str

        @model_validator(mode="after")
        def passwords_match(self) -> "PasswordChangeSerializer":
            if self.password != self.confirm_password:
                raise ValueError("Passwords do not match")
            return self
"""

from __future__ import annotations

import contextlib
import datetime
import uuid
from decimal import Decimal
from typing import Any, ClassVar, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)
from pydantic import (
    field_validator as pydantic_field_validator,
)
from pydantic import (
    model_validator as pydantic_model_validator,
)

from openviper.exceptions import DoesNotExist, ValidationError
from openviper.storage import default_storage

T = TypeVar("T", bound="Serializer")

# Re-export Pydantic validators for convenience
field_validator = pydantic_field_validator
model_validator = pydantic_model_validator


class Serializer(BaseModel):
    """Base class for all OpenViper serializers.

    Extends :class:`pydantic.BaseModel` with:

    * ``from_orm()`` — build from any ORM model using attribute access.
    * ``validate()`` — class-method parse that raises :class:`~openviper.exceptions.ValidationError`
      (not the Pydantic variant) on failure.
    * ``serialize()`` — return a JSON-safe dict via ``model_dump()``.
    * ``serialize_many()`` — serialize a list of objects.

    Field Validation
    ----------------
    Use the ``@field_validator`` decorator to validate individual fields::

        from openviper.serializers import Serializer, field_validator

        class UserSerializer(Serializer):
            username: str
            email: str

            @field_validator("username")
            @classmethod
            def validate_username(cls, v: str) -> str:
                if len(v) < 3:
                    raise ValueError("Username must be at least 3 characters")
                return v.lower()

            @field_validator("email")
            @classmethod
            def validate_email(cls, v: str) -> str:
                if "@" not in v:
                    raise ValueError("Invalid email address")
                return v

    Model Validation
    ----------------
    Use the ``@model_validator`` decorator to validate across multiple fields::

        from openviper.serializers import Serializer, model_validator

        class PasswordSerializer(Serializer):
            password: str
            confirm_password: str

            @model_validator(mode="after")
            def passwords_match(self) -> "PasswordSerializer":
                if self.password != self.confirm_password:
                    raise ValueError("Passwords do not match")
                return self
    """

    model_config = ConfigDict(
        from_attributes=True,  # enables ORM mode
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    # Subclasses may list field names that should be read-only (never set on create/update)
    read_only_fields: ClassVar[tuple[str, ...]] = ()
    # Fields to exclude from serialization output by default
    write_only_fields: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def validate(cls: type[T], data: Any) -> T:
        """Parse *data* into this serializer, raising
        :class:`~openviper.exceptions.ValidationError`."""
        try:
            return cls.model_validate(data)
        except PydanticValidationError as exc:
            errors = []
            for error in exc.errors(include_url=False):
                loc = ".".join(str(item) for item in error["loc"]) if error["loc"] else "__all__"
                errors.append({"field": loc, "message": error["msg"], "type": error["type"]})
            raise ValidationError(errors=errors) from exc

    @classmethod
    def validate_json_string(cls: type[T], json_str: str) -> T:
        """Parse a raw JSON string."""
        try:
            return cls.model_validate_json(json_str)
        except PydanticValidationError as exc:
            errors = []
            for error in exc.errors(include_url=False):
                loc = ".".join(str(item) for item in error["loc"]) if error["loc"] else "__all__"
                errors.append({"field": loc, "message": error["msg"], "type": error["type"]})
            raise ValidationError(errors=errors) from exc

    @classmethod
    def from_orm(cls: type[T], obj: Any) -> T:
        """Construct from an ORM object (requires ``from_attributes=True``)."""
        return cls.model_validate(obj)

    @classmethod
    def from_orm_many(cls: type[T], objs: list[Any]) -> list[T]:
        """Construct a list of serializer instances from a list of ORM objects."""
        return [cls.from_orm(obj) for obj in objs]

    def serialize(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Return a JSON-safe dict, automatically excluding write-only fields."""
        excluded: set[str] = set(self.write_only_fields)
        if exclude:
            excluded |= exclude
        return self.model_dump(mode="json", exclude=excluded or None)

    @classmethod
    def serialize_many(
        cls: type[T],
        objs: list[Any],
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Serialize a list of ORM objects to a list of dicts."""
        return [cls.from_orm(obj).serialize(exclude=exclude) for obj in objs]

    def serialize_json(self, *, exclude: set[str] | None = None) -> bytes:
        """
        Return JSON bytes via pydantic-core's Rust encoder.
        """
        excluded: set[str] = set(self.write_only_fields)
        if exclude:
            excluded |= exclude
        return self.model_dump_json(exclude=excluded or None).encode()

    @classmethod
    def serialize_many_json(
        cls: type[T],
        objs: list[Any],
        *,
        exclude: set[str] | None = None,
    ) -> bytes:
        """
        Serialize a list of ORM objects to a JSON bytes array.
        """
        excluded: set[str] = set(cls.write_only_fields)
        if exclude:
            excluded |= exclude
        excl = excluded or None
        parts = [cls.model_validate(obj).model_dump_json(exclude=excl) for obj in objs]
        return ("[" + ",".join(parts) + "]").encode()


# ── Field-type mapping ────────────────────────────────────────────────────────

# Mapping from ORM field class names to Python type annotations.
# Kept as a function so it's evaluated lazily (no circular import issues).

_FIELD_TYPE_MAP: dict[str, type] = {
    "AutoField": int,
    "IntegerField": int,
    "BigIntegerField": int,
    "PositiveIntegerField": int,
    "FloatField": float,
    "DecimalField": Decimal,
    "CharField": str,
    "TextField": str,
    "EmailField": str,
    "SlugField": str,
    "URLField": str,
    "IPAddressField": str,
    "BooleanField": bool,
    "DateTimeField": datetime.datetime,
    "DateField": datetime.date,
    "TimeField": datetime.time,
    "UUIDField": uuid.UUID,
    "JSONField": Any,
    "ForeignKey": int,
    "OneToOneField": int,
    "FileField": str,
    "ImageField": str,
}

# ORM field class names that represent file uploads.
_FILE_FIELD_TYPES: frozenset[str] = frozenset({"FileField", "ImageField"})


def _python_type_for_field(field: Any) -> type:
    """Return the Python type annotation for an ORM field instance."""
    cls_name = type(field).__name__
    return _FIELD_TYPE_MAP.get(cls_name, Any)


def _field_is_optional(field: Any) -> bool:
    """Return ``True`` if the field allows ``None``."""
    if getattr(field, "primary_key", False):
        return True  # PK is auto-generated, so optional on create
    if getattr(field, "null", False):
        return True
    if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
        return True
    return field.default is not None


class _ModelSerializerMeta(type(BaseModel)):
    """Metaclass for :class:`ModelSerializer`.

    At class-creation time it reads ``Meta.model`` / ``Meta.fields`` /
    ``Meta.exclude`` and builds Pydantic ``model_fields`` automatically.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> _ModelSerializerMeta:
        meta = namespace.get("Meta")
        model = getattr(meta, "model", None) if meta else None

        if model is None:
            # Abstract base – nothing to auto-generate
            return super().__new__(mcs, name, bases, namespace, **kwargs)

        # Determine which fields to include
        fields_opt: str | list[str] = getattr(meta, "fields", "__all__")
        exclude_opt: list[str] | tuple[str, ...] = getattr(meta, "exclude", ())
        read_only: tuple[str, ...] = getattr(meta, "read_only_fields", ())
        extra_kwargs: dict[str, dict[str, Any]] = getattr(meta, "extra_kwargs", {})

        model_fields: dict[str, Any] = getattr(model, "_fields", {})

        field_names = list(model_fields.keys()) if fields_opt == "__all__" else list(fields_opt)

        # Remove excluded fields
        field_names = [f for f in field_names if f not in exclude_opt]

        # Collect annotations + defaults from model fields
        annotations: dict[str, Any] = namespace.get("__annotations__", {})
        for field_name in field_names:
            # Skip fields already explicitly declared on the serializer
            if field_name in annotations or field_name in namespace:
                continue

            orm_field = model_fields.get(field_name)
            if orm_field is None:
                continue

            py_type = _python_type_for_field(orm_field)
            optional = _field_is_optional(orm_field)

            # Apply extra_kwargs overrides
            field_extra = extra_kwargs.get(field_name, {})
            if field_extra.get("required") is False:
                optional = True

            if optional:
                annotations[field_name] = py_type | None
                if field_name not in namespace:
                    namespace[field_name] = None
            else:
                annotations[field_name] = py_type

        namespace["__annotations__"] = annotations

        # Wire up read_only_fields & write_only_fields as ClassVars
        if read_only and "read_only_fields" not in namespace:
            namespace["read_only_fields"] = read_only

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # Stash the model reference for convenience
        cls._model = model  # type: ignore[attr-defined]

        return cls


class ModelSerializer(Serializer, metaclass=_ModelSerializerMeta):
    """Auto-generated serializer that derives fields from a OpenViper ``Model``.

    Subclass and define an inner ``Meta`` class:

    .. code-block:: python

        class BlogSerializer(ModelSerializer):
            class Meta:
                model = Blog
                fields = "__all__"          # or ["title", "body"]
                # exclude = ["secret"]      # alternative to ``fields``
                # read_only_fields = ("id", "created_at")
                # extra_kwargs = {"title": {"required": False}}

    ``ModelSerializer`` inherits every helper from :class:`Serializer`
    (``validate()``, ``from_orm()``, ``serialize()``, etc.).
    """

    _model: ClassVar[type]  # set by metaclass

    # ── File-field helpers ────────────────────────────────────────────────

    @classmethod
    def _get_file_fields(cls) -> dict[str, Any]:
        """Return a mapping of field_name -> ORM field for file-type fields."""
        model_fields: dict[str, Any] = getattr(cls._model, "_fields", {})
        return {
            name: field
            for name, field in model_fields.items()
            if type(field).__name__ in _FILE_FIELD_TYPES
        }

    @classmethod
    def _validate_file_sizes(cls, data: dict[str, Any]) -> None:
        """Raise :class:`~openviper.exceptions.ValidationError`
        if any file value exceeds its limit."""
        file_fields = cls._get_file_fields()
        errors: list[dict[str, str]] = []
        for name, orm_field in file_fields.items():
            value = data.get(name)
            if value is None or isinstance(value, str):
                continue
            try:
                orm_field.validate(value)
            except ValueError as exc:
                errors.append({"field": name, "message": str(exc), "type": "file_size"})
        if errors:
            raise ValidationError(errors=errors)

    @classmethod
    async def _persist_files(
        cls,
        data: dict[str, Any],
        *,
        old_instance: Any | None = None,
    ) -> dict[str, Any]:
        """Save file values through the storage backend and replace with paths.

        Returns a copy of *data* with file values replaced by their stored paths.
        On update, if *old_instance* is provided and the file has changed, the
        previous file is deleted from storage.
        """
        # Inline import to avoid circular dependency at module level

        file_fields = cls._get_file_fields()
        if not file_fields:
            return data

        result = dict(data)
        for name, orm_field in file_fields.items():
            value = result.get(name)
            if value is None or isinstance(value, str):
                continue

            # Determine filename
            filename = getattr(value, "filename", None) or getattr(value, "name", None) or "file"
            upload_to = getattr(orm_field, "upload_to", "uploads/")
            target_name = f"{upload_to}{filename}"

            # Read bytes from value
            if isinstance(value, bytes):
                content = value
            elif hasattr(value, "read"):
                content = value.read()
                if hasattr(content, "__await__"):
                    content = await content
            else:
                content = bytes(value)

            # Delete old file on update if path changed
            if old_instance is not None:
                old_path = getattr(old_instance, name, None)
                if old_path and isinstance(old_path, str):
                    with contextlib.suppress(Exception):
                        await default_storage.delete(old_path)

            # Persist
            saved_path = await default_storage.save(target_name, content)
            result[name] = saved_path

        return result

    # ── CRUD helpers ──────────────────────────────────────────────────────

    async def create(self) -> Any:
        """Persist a new model instance from the validated data.

        Returns the saved model instance.
        """
        data = self.model_dump(exclude_none=False)
        # Remove read-only fields and None PKs before create
        for f in self.read_only_fields:
            data.pop(f, None)
        pk_val = data.get("id")
        if pk_val is None:
            data.pop("id", None)

        # Validate & persist uploaded files
        self._validate_file_sizes(data)
        data = await self._persist_files(data)

        return await self._model.objects.create(**data)

    async def update(self, instance: Any) -> Any:
        """Apply validated data to an existing model *instance* and save.

        Returns the updated model instance.
        """
        data = self.model_dump(exclude_none=False)
        for f in self.read_only_fields:
            data.pop(f, None)
        data.pop("id", None)  # never update the PK

        # Validate & persist uploaded files (with old-file cleanup)
        self._validate_file_sizes(data)
        data = await self._persist_files(data, old_instance=instance)

        for attr, value in data.items():
            setattr(instance, attr, value)
        await instance.save()
        return instance

    async def save(self, instance: Any | None = None) -> dict[str, Any]:
        """Create or update a model instance and return serialized data.

        Behaviour:

        * If *instance* is provided explicitly -> update that instance.
        * If the validated data contains a non-``None`` ``id`` / ``pk`` ->
          fetch the existing record and update it.
        * Otherwise -> create a new record.

        Returns:
            A JSON-safe ``dict`` of the persisted model instance.
        """

        if instance is not None:
            obj = await self.update(instance)
            return type(self).from_orm(obj).serialize()

        # Auto-detect create vs update from PK in data
        pk_value = getattr(self, "id", None)
        if pk_value is None:
            pk_value = getattr(self, "pk", None)

        if pk_value is not None:
            # Attempt to fetch existing record
            try:
                existing = await self._model.objects.get(id=pk_value)
            except DoesNotExist:
                existing = None

            if existing is not None:
                obj = await self.update(existing)
                return type(self).from_orm(obj).serialize()

        # Create
        obj = await self.create()
        return type(self).from_orm(obj).serialize()


class PaginatedSerializer(BaseModel):
    """Envelope for paginated list responses."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[Any]
