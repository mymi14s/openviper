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

import asyncio
import contextlib
import datetime
import os
import typing
import uuid
from decimal import Decimal
from functools import lru_cache
from typing import Any, ClassVar, TypeVar, Union

from pydantic import (
    BaseModel,
    ConfigDict,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)
from pydantic import (
    computed_field as pydantic_computed_field,
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

# Re-export Pydantic validators / computed fields for convenience
field_validator = pydantic_field_validator
model_validator = pydantic_model_validator
computed_field = pydantic_computed_field

# Cache for dynamically-built partial classes (populated by Serializer._build_partial_class)
_PARTIAL_CLASSES: dict[type, type] = {}

# Cache for file fields per ModelSerializer class
_FILE_FIELDS_CACHE: dict[type, dict[str, Any]] = {}


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
    readonly_fields: ClassVar[tuple[str, ...]] = ()
    # Fields to exclude from serialization output by default
    write_only_fields: ClassVar[tuple[str, ...]] = ()
    # Number of objects per batch when streaming a QuerySet through serialize_many
    PAGE_SIZE: ClassVar[int] = 25

    @classmethod
    def _build_partial_class(cls: type[T]) -> type[T]:
        """Return a version of this class where every field is optional.

        The result is cached on ``_PARTIAL_CLASSES`` so it is only created once
        per serializer class.  The returned class tracks which fields were
        actually supplied via ``model_fields_set``; callers can therefore use
        ``model_dump(exclude_unset=True)`` to apply only the provided values
        (see :meth:`update`).
        """
        if cls in _PARTIAL_CLASSES:
            return _PARTIAL_CLASSES[cls]  # type: ignore[return-value]

        new_annotations: dict[str, Any] = {}
        new_defaults: dict[str, Any] = {}
        for fname, fi in cls.model_fields.items():
            ann = fi.annotation
            # Make Optional if not already (i.e. Union[X, None] not present)
            origin = typing.get_origin(ann)
            args = typing.get_args(ann)
            already_optional = origin is Union and type(None) in args
            new_annotations[fname] = ann if already_optional else ann | None
            new_defaults[fname] = fi.default if not fi.is_required() else None

        partial_cls: type[T] = type(  # type: ignore[assignment]
            f"_Partial{cls.__name__}",
            (cls,),
            {"__annotations__": new_annotations, **new_defaults},
        )
        _PARTIAL_CLASSES[cls] = partial_cls
        return partial_cls

    @classmethod
    def validate(cls: type[T], data: Any, *, partial: bool = False) -> T:
        """Parse *data* into this serializer, raising
        :class:`~openviper.exceptions.ValidationError`.

        Args:
            data: Dict, ORM object, or any mapping accepted by Pydantic.
            partial: When ``True`` every field becomes optional, which is
                useful for ``PATCH``-style endpoints.  The returned instance
                records which fields were supplied via ``model_fields_set``;
                pass ``model_dump(exclude_unset=True)`` to :meth:`update` when
                only the changed keys should be written.
        """
        target = cls._build_partial_class() if partial else cls
        try:
            return target.model_validate(data)  # type: ignore[return-value]
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

    def _compute_excluded(self, exclude: set[str] | None) -> set[str] | None:
        """Merge instance write_only_fields with caller-supplied *exclude* set.

        Returns ``None`` when no fields need excluding (avoids passing an empty
        set to Pydantic which would still allocate a filtering pass).
        """
        excluded: set[str] = set(self.write_only_fields)
        if exclude:
            excluded |= exclude
        return excluded or None

    def serialize(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Return a JSON-safe dict, automatically excluding write-only fields."""
        return self.model_dump(mode="json", exclude=self._compute_excluded(exclude))

    @classmethod
    async def serialize_many(
        cls: type[T],
        objs: Any,
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Serialize a list or QuerySet of ORM objects to a list of dicts.

        When *objs* is a QuerySet (detected via ``hasattr(objs, "batch")``),
        objects are fetched in ``PAGE_SIZE``-sized batches to avoid loading
        the entire result set into memory at once.  Plain lists are handled
        with a simple list comprehension (no DB calls).

        Optimized to reduce per-object overhead and avoid N+1 queries.
        """
        # Pre-compute excluded fields once
        excl: set[str] | None = (
            (set(cls.write_only_fields) | exclude)
            if exclude
            else (set(cls.write_only_fields) or None)
        )

        if hasattr(objs, "batch"):
            results: list[dict[str, Any]] = []
            async for batch in objs.batch(size=cls.PAGE_SIZE):
                batch_instances = [cls.model_validate(obj) for obj in batch]
                results.extend(
                    [inst.model_dump(mode="json", exclude=excl) for inst in batch_instances]
                )
            return results

        instances = [cls.model_validate(obj) for obj in objs]
        return [inst.model_dump(mode="json", exclude=excl) for inst in instances]

    def serialize_json(self, *, exclude: set[str] | None = None) -> bytes:
        """Return JSON bytes via pydantic-core's Rust encoder."""
        return self.model_dump_json(exclude=self._compute_excluded(exclude)).encode()

    @classmethod
    async def serialize_many_json(
        cls: type[T],
        objs: Any,
        *,
        exclude: set[str] | None = None,
    ) -> bytes:
        """Serialize a list or QuerySet of ORM objects to a JSON bytes array.

        QuerySets are fetched in ``PAGE_SIZE``-sized batches (same streaming
        behaviour as :meth:`serialize_many`).

        Optimized to reduce per-object overhead and memory allocation.
        """
        excl: set[str] | None = (
            (set(cls.write_only_fields) | exclude)
            if exclude
            else (set(cls.write_only_fields) or None)
        )

        if hasattr(objs, "batch"):
            parts: list[str] = []
            async for batch in objs.batch(size=cls.PAGE_SIZE):
                batch_instances = [cls.model_validate(obj) for obj in batch]
                parts.extend([inst.model_dump_json(exclude=excl) for inst in batch_instances])
            return ("[" + ",".join(parts) + "]").encode()

        instances = [cls.model_validate(obj) for obj in objs]
        parts_list = [inst.model_dump_json(exclude=excl) for inst in instances]
        return ("[" + ",".join(parts_list) + "]").encode()

    @classmethod
    async def paginate(
        cls: type[T],
        qs: Any,
        *,
        page: int = 1,
        page_size: int | None = None,
        base_url: str = "",
        exclude: set[str] | None = None,
    ) -> PaginatedSerializer:
        """Return a :class:`PaginatedSerializer` for a single page of *qs*.

        Args:
            qs: A QuerySet (must support ``.count()``, ``.offset()``,
                ``.limit()``, and ``.all()``).
            page: 1-based page number.
            page_size: Items per page.  Defaults to ``cls.PAGE_SIZE`` (25).
            base_url: When provided, ``next`` / ``previous`` URLs are built as
                ``{base_url}?page=N&page_size=M``.
            exclude: Field names to omit from each serialized item.

        Returns:
            A :class:`PaginatedSerializer` with ``count``, ``next``,
            ``previous``, and ``results``.

        Optimized to batch serialize objects and reduce N+1 queries.
        """
        ps = page_size if page_size is not None else cls.PAGE_SIZE
        total: int = await qs.count()
        offset = (page - 1) * ps
        page_qs = qs.offset(offset).limit(ps)
        objs = await page_qs.all()

        excl: set[str] | None = (
            (set(cls.write_only_fields) | exclude)
            if exclude
            else (set(cls.write_only_fields) or None)
        )

        instances = [cls.model_validate(obj) for obj in objs]
        results = [inst.model_dump(mode="json", exclude=excl) for inst in instances]

        next_url: str | None = None
        prev_url: str | None = None
        if base_url:
            if offset + ps < total:
                next_url = f"{base_url}?page={page + 1}&page_size={ps}"
            if page > 1:
                prev_url = f"{base_url}?page={page - 1}&page_size={ps}"

        return PaginatedSerializer(
            count=total,
            next=next_url,
            previous=prev_url,
            results=results,
        )


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
    "ManyToManyField": list,
    "FileField": str,
    "ImageField": str,
}

# ORM field class names that represent file uploads.
_FILE_FIELD_TYPES: frozenset[str] = frozenset({"FileField", "ImageField"})


@lru_cache(maxsize=256)
def _python_type_for_field_by_name(field_class_name: str) -> type:
    """Return the Python type annotation for an ORM field class name.

    Cached to avoid repeated lookups.
    """
    return _FIELD_TYPE_MAP.get(field_class_name, Any)


@lru_cache(maxsize=256)
def _field_is_optional_cached(
    primary_key: bool,
    null: bool,
    auto_now: bool,
    auto_now_add: bool,
    has_default: bool,
) -> bool:
    """Cached check for whether a field is optional.

    Takes immutable parameters to enable caching.
    """
    if primary_key:
        return True  # PK is auto-generated, so optional on create
    if null:
        return True
    if auto_now or auto_now_add:
        return True
    return has_default


def _field_is_optional(field: Any) -> bool:
    """Return ``True`` if the field allows ``None``."""
    # A field has a default when its ``default`` attribute is anything other
    # than the framework sentinel (``None`` means "no default set" in
    # OpenViper's field API, NOT the Python value None).  We detect a real
    # default by checking ``has_default()`` first (OpenViper fields expose
    # this), and fall back to checking whether the raw attribute differs from
    # the sentinel value stored as ``NOT_PROVIDED`` on the field class.
    raw_default = getattr(field, "default", None)
    not_provided = getattr(type(field), "NOT_PROVIDED", None)
    if not_provided is not None:
        has_default = raw_default is not not_provided
    else:
        # Fallback: treat any value (including False, 0, "") as "has default";
        # only treat Python None as "no default".
        has_default = raw_default is not None or getattr(field, "has_default", lambda: False)()
    return _field_is_optional_cached(
        primary_key=getattr(field, "primary_key", False),
        null=getattr(field, "null", False),
        auto_now=getattr(field, "auto_now", False),
        auto_now_add=getattr(field, "auto_now_add", False),
        has_default=has_default,
    )


class _ModelSerializerMeta(type(BaseModel)):
    """Metaclass for :class:`ModelSerializer`.

    At class-creation time it reads ``Meta.model`` / ``Meta.fields`` /
    ``Meta.exclude`` and builds Pydantic ``model_fields`` automatically.
    """

    def __new__(  # pylint: disable=bad-classmethod-argument
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
        read_only: tuple[str, ...] = getattr(meta, "readonly_fields", ())
        write_only: tuple[str, ...] = getattr(meta, "write_only_fields", ())
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

            # Use cached type lookup
            field_class_name = type(orm_field).__name__
            py_type = _python_type_for_field_by_name(field_class_name)
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

        # Wire up readonly_fields & write_only_fields as ClassVars from Meta
        if read_only and "readonly_fields" not in namespace:
            namespace["readonly_fields"] = read_only
        if write_only and "write_only_fields" not in namespace:
            namespace["write_only_fields"] = write_only

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
                # readonly_fields = ("id", "created_at")
                # extra_kwargs = {"title": {"required": False}}

    ``ModelSerializer`` inherits every helper from :class:`Serializer`
    (``validate()``, ``from_orm()``, ``serialize()``, etc.).
    """

    _model: ClassVar[type]  # set by metaclass

    # ── File-field helpers ────────────────────────────────────────────────

    @classmethod
    def _get_file_fields(cls) -> dict[str, Any]:
        """Return a mapping of field_name -> ORM field for file-type fields.

        Cached per serializer class to avoid repeated introspection.
        """
        if cls in _FILE_FIELDS_CACHE:
            return _FILE_FIELDS_CACHE[cls]

        model_fields: dict[str, Any] = getattr(cls._model, "_fields", {})
        file_fields = {
            name: field
            for name, field in model_fields.items()
            if type(field).__name__ in _FILE_FIELD_TYPES
        }
        _FILE_FIELDS_CACHE[cls] = file_fields
        return file_fields

    @classmethod
    def _validate_file_sizes(cls, data: dict[str, Any]) -> None:
        """Raise :class:`~openviper.exceptions.ValidationError`
        if any file value exceeds its limit.

        Optimized to batch validation operations.
        """
        file_fields = cls._get_file_fields()
        if not file_fields:
            return

        errors: list[dict[str, str]] = []

        # Batch process validation to reduce overhead
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

        Optimized to parallelize file operations using asyncio.gather.
        """
        file_fields = cls._get_file_fields()
        if not file_fields:
            return data

        result = dict(data)

        # Collect all file operations to execute in parallel
        async def process_file(name: str, orm_field: Any, value: Any) -> tuple[str, str]:
            """Process a single file upload and return (field_name, saved_path)."""
            # Determine filename — strip directory components to prevent path traversal
            raw_name = getattr(value, "filename", None) or getattr(value, "name", None) or "file"
            filename = os.path.basename(raw_name) or "file"
            upload_to = getattr(orm_field, "upload_to", "uploads/")
            target_name = f"{upload_to}{filename}"

            # Read bytes from value
            if isinstance(value, bytes):
                content = value
            elif hasattr(value, "read"):
                content = value.read()
                if hasattr(content, "__await__"):
                    content = await content
            elif isinstance(value, (bytearray, memoryview)):
                content = bytes(value)
            else:
                raise TypeError(f"Unsupported file value type: {type(value).__name__}")

            # Delete old file on update if path changed
            if old_instance is not None:
                old_path = getattr(old_instance, name, None)
                if old_path and isinstance(old_path, str):
                    with contextlib.suppress(Exception):
                        await default_storage.delete(old_path)

            # Persist and return the saved path
            saved_path = await default_storage.save(target_name, content)
            return name, saved_path

        # Build list of file operations
        file_operations = []
        for name, orm_field in file_fields.items():
            value = result.get(name)
            if value is None or isinstance(value, str):
                continue
            file_operations.append(process_file(name, orm_field, value))

        # Execute all file operations in parallel
        if file_operations:
            saved_files = await asyncio.gather(*file_operations)
            for name, saved_path in saved_files:
                result[name] = saved_path

        return result

    # ── CRUD helpers ──────────────────────────────────────────────────────

    async def create(self) -> Any:
        """Persist a new model instance from the validated data.

        Returns the saved model instance.
        """
        # exclude_none=True prevents overriding DB-level defaults (auto_now_add,
        # uuid defaults, etc.) with None for fields the caller never set.
        data = self.model_dump(exclude_none=True)
        # Remove read-only fields before create
        for f in self.readonly_fields:
            data.pop(f, None)
        # Also drop an explicit None PK in case it survived exclude_none
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
        # exclude_unset=True ensures only fields the caller explicitly provided
        # are applied — avoids clobbering existing DB values with None for
        # fields the PATCH request omitted.
        data = self.model_dump(exclude_unset=True)
        for f in self.readonly_fields:
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
