"""Pydantic-based serializer base for OpenViper.

Provides :class:`Serializer` as a thin wrapper over :class:`pydantic.BaseModel`
and :class:`ModelSerializer` which auto-generates Pydantic fields from an ORM
:class:`~openviper.db.models.Model` at class-creation time.
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

import orjson
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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

from openviper.core.context import current_user
from openviper.db.fields import ForeignKey
from openviper.db.models import Q, _build_keyset_q, _cursor_decode, _cursor_encode
from openviper.exceptions import DoesNotExist, PermissionDenied, ValidationError
from openviper.storage import default_storage

T = TypeVar("T", bound="Serializer")

# Re-export Pydantic validators / computed fields for convenience
field_validator = pydantic_field_validator
model_validator = pydantic_model_validator
computed_field = pydantic_computed_field


def _map_pydantic_errors(exc: PydanticValidationError) -> ValidationError:
    """Convert a PydanticValidationError to a OpenViper ValidationError."""
    return ValidationError(
        errors=[
            {
                "field": ".".join(str(i) for i in e["loc"]) if e["loc"] else "__all__",
                "message": e["msg"],
                "type": e["type"],
            }
            for e in exc.errors(include_url=False)
        ]
    )


# Cache for dynamically-built partial classes (populated by Serializer._build_partial_class)
_PARTIAL_CLASSES: dict[type, type] = {}


class Serializer(BaseModel):
    """Base serializer backed by :class:`pydantic.BaseModel`.

    Adds ``from_orm()``, ``validate()``, ``serialize()``, and
    ``serialize_many()`` on top of standard Pydantic functionality.
    Raises :class:`~openviper.exceptions.ValidationError` instead of the
    Pydantic variant on validation failure.
    """

    model_config = ConfigDict(
        from_attributes=True,  # enables ORM mode
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    # Subclasses may list field names that should be read-only (never set on create/update)
    readonly_fields: ClassVar[tuple[str, ...]] = ()
    # Fields excluded from serialization output by default
    writeonly_fields: ClassVar[tuple[str, ...]] = ()
    # Number of objects per batch when streaming a QuerySet through serialize_many
    PAGE_SIZE: ClassVar[int] = 25
    MAX_PAGE_SIZE: ClassVar[int] = 1000
    # List of permission classes to apply to this serializer
    permission_classes: ClassVar[list[Any]] = []

    def __init__(self, **data: Any) -> None:
        context = data.pop("_context", {})
        super().__init__(**data)
        object.__setattr__(self, "_context", context)

    @property
    def context(self) -> dict[str, Any]:
        return getattr(self, "_context", {})

    async def check_permissions(self) -> None:
        """Evaluate all ``permission_classes`` against the current request.

        Raises :class:`~openviper.exceptions.PermissionDenied` on the first
        failing permission.  Returns immediately when no request is bound to
        the serializer context and no ambient user is present.
        """
        request = self.context.get("request")
        if request is None and current_user.get() is None:
            return

        for permission_class in self.permission_classes:
            permission = permission_class()
            if not await permission.has_permission(request, self):
                self.permission_denied(request)

    def permission_denied(self, request: Any, message: str | None = None) -> None:
        """Raise a PermissionDenied exception."""
        raise PermissionDenied(message or "Permission denied.")

    @classmethod
    def _get_excluded_fields(cls, exclude: set[str] | None = None) -> frozenset[str]:
        """Return ``writeonly_fields`` merged with *exclude* as a frozen set."""
        if not cls.writeonly_fields and not exclude:
            return frozenset()
        result = set(cls.writeonly_fields)
        if exclude:
            result |= exclude
        return frozenset(result)

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Convert a value to a JSON-serializable type.

        Handles Decimal, datetime, date, time, UUID, bytes, and other
        non-JSON-serializable types that commonly appear in ORM fields.
        """
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, (list, tuple)):
            return [Serializer._serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: Serializer._serialize_value(v) for k, v in value.items()}
        return value

    @classmethod
    def _obj_to_dict(cls, obj: Any, excl: frozenset[str]) -> dict[str, Any]:
        """Map a single ORM object to a JSON-safe dict, skipping excluded fields."""
        return {
            fname: cls._serialize_value(getattr(obj, fname, None))
            for fname in cls.model_fields
            if fname not in excl
        }

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
    def validate(
        cls: type[T], data: Any, *, partial: bool = False, context: dict[str, Any] | None = None
    ) -> T:
        """Parse *data* into this serializer, raising
        :class:`~openviper.exceptions.ValidationError`.

        Args:
            data: Dict, ORM object, or any mapping accepted by Pydantic.
            partial: When ``True`` every field becomes optional, which is
                useful for ``PATCH``-style endpoints.  The returned instance
                records which fields were supplied via ``model_fields_set``;
                pass ``model_dump(exclude_unset=True)`` to :meth:`update` when
                only the changed keys should be written.
            context: Optional dictionary of extra context (e.g. {'request': request}).
        """
        target = cls._build_partial_class() if partial else cls
        try:
            if isinstance(data, dict):
                return target(**data, _context=context or {})  # type: ignore[return-value]
            return target.model_validate(data, context=context)  # type: ignore[return-value]
        except PydanticValidationError as exc:
            raise _map_pydantic_errors(exc) from exc

    @classmethod
    def validate_json_string(cls: type[T], json_str: str) -> T:
        """Parse a raw JSON string."""
        try:
            return cls.model_validate_json(json_str)
        except PydanticValidationError as exc:
            raise _map_pydantic_errors(exc) from exc

    @classmethod
    def from_orm(cls: type[T], obj: Any) -> T:
        """Construct from an ORM object (requires ``from_attributes=True``)."""
        orm_fields: dict[str, Any] = getattr(obj.__class__, "_fields", {})
        if not orm_fields:
            return cls.model_validate(obj)
        data: dict[str, Any] = {}
        for fname in cls.model_fields:
            orm_field = orm_fields.get(fname)
            if isinstance(orm_field, ForeignKey):
                data[fname] = obj.__dict__.get(orm_field.column_name)
            else:
                data[fname] = getattr(obj, fname, None)
        return cls.model_validate(data)

    @classmethod
    def from_orm_many(cls: type[T], objs: list[Any]) -> list[T]:
        """Construct a list of serializer instances from a list of ORM objects."""
        return [cls.from_orm(obj) for obj in objs]

    def _compute_excluded(self, exclude: set[str] | None) -> set[str] | None:
        """Return ``writeonly_fields`` merged with *exclude*, or ``None`` when empty."""
        excluded: set[str] = set(self.writeonly_fields)
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
        """
        excl = cls._get_excluded_fields(exclude)

        if hasattr(objs, "batch"):
            results: list[dict[str, Any]] = []
            async for batch in objs.batch(size=cls.PAGE_SIZE):
                results.extend(cls._obj_to_dict(obj, excl) for obj in batch)
            return results

        return [cls._obj_to_dict(obj, excl) for obj in objs]

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
        """
        excl = cls._get_excluded_fields(exclude)

        if hasattr(objs, "batch"):
            parts: list[dict[str, Any]] = []
            async for batch in objs.batch(size=cls.PAGE_SIZE):
                parts.extend(cls._obj_to_dict(obj, excl) for obj in batch)
            return orjson.dumps(parts)

        return orjson.dumps([cls._obj_to_dict(obj, excl) for obj in objs])

    @classmethod
    async def paginate(
        cls: type[T],
        qs: Any,
        *,
        page: int = 1,
        page_size: int | None = None,
        cursor: str | None = None,
        base_url: str = "",
        exclude: set[str] | None = None,
    ) -> PaginatedSerializer:
        """Return a :class:`PaginatedSerializer` for a single page of *qs*.

        When *cursor* is supplied the query uses keyset pagination — the
        database seeks directly to the cursor position so performance is
        O(log N) regardless of page depth.  The response will include
        ``next_cursor`` for the next page.

        When *cursor* is omitted the query falls back to OFFSET-based
        pagination (backward-compatible).

        Args:
            qs: A QuerySet.
            page: 1-based page number (OFFSET mode only).
            page_size: Items per page.  Defaults to ``cls.PAGE_SIZE`` (25).
            cursor: Opaque keyset cursor from a previous response.
            base_url: When provided, ``next`` / ``previous`` URLs are built.
            exclude: Field names to omit from each serialized item.

        Returns:
            A :class:`PaginatedSerializer` with ``count``, ``next``,
            ``previous``, ``results``, and optionally ``next_cursor``.
        """
        ps = page_size if page_size is not None else cls.PAGE_SIZE
        ps = max(1, min(ps, cls.MAX_PAGE_SIZE))
        page = max(1, page)

        excl = cls._get_excluded_fields(exclude)

        if cursor is not None:
            # Keyset path: O(log N) — no OFFSET.
            # COUNT and the page fetch run concurrently; neither depends on the other.
            cursor_values = _cursor_decode(cursor)
            order_fields: list[str] = list(getattr(qs, "_order", []))
            keyset_q: Q | None = (
                _build_keyset_q(order_fields, cursor_values)
                if cursor_values and order_fields
                else None
            )
            page_qs = qs.filter(keyset_q) if keyset_q is not None else qs

            total, objs = await asyncio.gather(
                qs.count(),
                page_qs.limit(ps).all(),
            )

            next_cur: str | None = None
            if len(objs) == ps and order_fields:
                last = objs[-1]
                next_cur = _cursor_encode(
                    {f.lstrip("-"): getattr(last, f.lstrip("-"), None) for f in order_fields}
                )

            next_url: str | None = (
                f"{base_url}?cursor={next_cur}&page_size={ps}" if base_url and next_cur else None
            )

            results = [cls._obj_to_dict(obj, excl) for obj in objs]
            return PaginatedSerializer(
                count=total,
                next=next_url,
                previous=None,
                results=results,
                next_cursor=next_cur,
            )

        # OFFSET path: used only for the first uncursored request (page 1).
        # COUNT and the page fetch run concurrently.
        offset = (page - 1) * ps
        page_qs = qs.offset(offset).limit(ps)

        total, objs = await asyncio.gather(
            qs.count(),
            page_qs.all(),
        )

        # Encode a cursor from the last item so subsequent requests use keyset pagination.
        order_fields_offset: list[str] = list(getattr(qs, "_order", []))
        next_cur_offset: str | None = None
        if len(objs) == ps and order_fields_offset:
            last = objs[-1]
            next_cur_offset = _cursor_encode(
                {f.lstrip("-"): getattr(last, f.lstrip("-"), None) for f in order_fields_offset}
            )

        # Generate traditional page-number URLs for backward compatibility.
        next_url = None
        prev_url = None
        if base_url:
            # For page-number URLs, prefer cursor if available (faster keyset navigation)
            if next_cur_offset and offset + ps < total:
                next_url = f"{base_url}?cursor={next_cur_offset}&page_size={ps}"
            elif offset + ps < total:
                next_url = f"{base_url}?page={page + 1}&page_size={ps}"
            if page > 1:
                prev_url = f"{base_url}?page={page - 1}&page_size={ps}"

        results = [cls._obj_to_dict(obj, excl) for obj in objs]

        return PaginatedSerializer(
            count=total,
            next=next_url,
            previous=prev_url,
            results=results,
            next_cursor=next_cur_offset,
        )


# ── Field-type mapping ────────────────────────────────────────────────────────

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

_FILE_FIELD_TYPES: frozenset[str] = frozenset({"FileField", "ImageField"})


@lru_cache(maxsize=256)
def _python_type_for_field_by_name(field_class_name: str) -> type:
    """Return the Python type annotation for an ORM field class name."""
    return _FIELD_TYPE_MAP.get(field_class_name, Any)


@lru_cache(maxsize=256)
def _field_is_optional_cached(
    primary_key: bool,
    null: bool,
    auto_now: bool,
    auto_now_add: bool,
    has_default: bool,
) -> bool:
    """Return ``True`` if a field with these attributes should be optional."""
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

        fields_opt: str | list[str] = getattr(meta, "fields", "__all__")
        exclude_opt: list[str] | tuple[str, ...] = getattr(meta, "exclude", ())
        read_only: tuple[str, ...] = getattr(meta, "readonly_fields", ())
        write_only: tuple[str, ...] = getattr(meta, "writeonly_fields", ())
        extra_kwargs: dict[str, dict[str, Any]] = getattr(meta, "extra_kwargs", {})

        model_fields: dict[str, Any] = getattr(model, "_fields", {})

        field_names = list(model_fields.keys()) if fields_opt == "__all__" else list(fields_opt)
        field_names = [f for f in field_names if f not in exclude_opt]

        annotations: dict[str, Any] = namespace.get("__annotations__", {})
        # 'required' is a serializer-level key; must not be forwarded to pydantic.Field().
        _serializer_only_keys = frozenset({"required"})

        for field_name in field_names:
            # Skip fields already explicitly declared on the serializer
            if field_name in annotations or field_name in namespace:
                continue

            orm_field = model_fields.get(field_name)
            if orm_field is None:
                continue

            field_class_name = type(orm_field).__name__
            py_type = _python_type_for_field_by_name(field_class_name)
            optional = _field_is_optional(orm_field)

            field_extra = extra_kwargs.get(field_name, {})
            if field_extra.get("required") is False:
                optional = True

            pydantic_field_kwargs = {
                k: v for k, v in field_extra.items() if k not in _serializer_only_keys
            }

            if optional:
                annotations[field_name] = py_type | None
                if field_name not in namespace:
                    namespace[field_name] = (
                        Field(None, **pydantic_field_kwargs) if pydantic_field_kwargs else None
                    )
            else:
                annotations[field_name] = py_type
                if pydantic_field_kwargs and field_name not in namespace:
                    namespace[field_name] = Field(**pydantic_field_kwargs)

        namespace["__annotations__"] = annotations

        if read_only and "readonly_fields" not in namespace:
            namespace["readonly_fields"] = read_only
        if write_only and "writeonly_fields" not in namespace:
            namespace["writeonly_fields"] = write_only

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        cls._model = model  # type: ignore[attr-defined]

        return cls


class ModelSerializer(Serializer, metaclass=_ModelSerializerMeta):
    """Serializer with fields auto-derived from a OpenViper :class:`~openviper.db.models.Model`.

    Requires an inner ``Meta`` class defining at minimum ``model`` and ``fields``.
    Supports ``exclude``, ``readonly_fields``, ``writeonly_fields``, and
    ``extra_kwargs`` (forwarded to :func:`pydantic.Field`).
    """

    _model: ClassVar[type]  # set by metaclass

    # ── File-field helpers ────────────────────────────────────────────────

    @classmethod
    @lru_cache(maxsize=512)
    def _get_file_fields(cls) -> dict[str, Any]:
        """Return a mapping of field_name -> ORM field for file-type fields.

        Cached with LRU eviction to prevent unbounded memory growth.
        """
        model_fields: dict[str, Any] = getattr(cls._model, "_fields", {})
        file_fields = {
            name: field
            for name, field in model_fields.items()
            if type(field).__name__ in _FILE_FIELD_TYPES
        }
        return file_fields

    @classmethod
    def _validate_file_sizes(cls, data: dict[str, Any]) -> None:
        """Raise :class:`~openviper.exceptions.ValidationError`
        if any file value exceeds its limit.
        """
        file_fields = cls._get_file_fields()
        if not file_fields:
            return

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
        file_fields = cls._get_file_fields()
        if not file_fields:
            return data

        result = dict(data)

        async def process_file(name: str, orm_field: Any, value: Any) -> tuple[str, str]:
            """Return (field_name, saved_path) after persisting the upload."""
            # Strip directory components to prevent path traversal.
            raw_name = getattr(value, "filename", None) or getattr(value, "name", None) or "file"
            filename = os.path.basename(raw_name) or "file"
            upload_to = getattr(orm_field, "upload_to", "uploads/")
            # Sanitize upload_to: strip leading slashes and collapse any '..' segments
            # to prevent a maliciously-configured field from writing outside the
            # storage root.
            norm_upload_to = os.path.normpath(upload_to.lstrip("/"))
            clean_parts = [p for p in norm_upload_to.split(os.sep) if p not in ("", ".", "..")]
            clean_upload_to = "/".join(clean_parts) if clean_parts else "uploads"
            target_name = f"{clean_upload_to}/{filename}"

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

            saved_path = await default_storage.save(target_name, content)
            return name, saved_path

        file_operations = []
        for name, orm_field in file_fields.items():
            value = result.get(name)
            if value is None or isinstance(value, str):
                continue
            file_operations.append(process_file(name, orm_field, value))

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
        await self.check_permissions()
        data = self.model_dump(exclude_none=True)
        for f in self.readonly_fields:
            data.pop(f, None)
        # exclude_none=True may pass an explicit None pk; drop it so the DB generates the value
        pk_val = data.get("id")
        if pk_val is None:
            data.pop("id", None)

        self._validate_file_sizes(data)
        data = await self._persist_files(data)

        return await self._model.objects.create(**data)

    async def update(self, instance: Any) -> Any:
        """Apply validated data to an existing model *instance* and save.

        Returns the updated model instance.
        """
        await self.check_permissions()
        data = self.model_dump(exclude_unset=True)
        for f in self.readonly_fields:
            data.pop(f, None)
        data.pop("id", None)  # never update the PK

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

        pk_value = getattr(self, "id", None)
        if pk_value is None:
            pk_value = getattr(self, "pk", None)

        if pk_value is not None:
            try:
                existing = await self._model.objects.get(id=pk_value)
            except DoesNotExist:
                existing = None

            if existing is not None:
                obj = await self.update(existing)
                return type(self).from_orm(obj).serialize()

        obj = await self.create()
        return type(self).from_orm(obj).serialize()


class PaginatedSerializer(BaseModel):
    """Envelope for paginated list responses."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[Any]
    next_cursor: str | None = None
