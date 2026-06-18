"""Pydantic-based serializer base for OpenViper.

Provides :class:`Serializer` as a thin wrapper over
:class:`pydantic.BaseModel` and :class:`ModelSerializer` which
auto-generates Pydantic fields from an ORM
:class:`~openviper.db.models.Model` at class-creation time.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import logging
import re
import typing
import uuid
from copy import copy
from decimal import Decimal
from functools import lru_cache
from types import MappingProxyType
from typing import Any, ClassVar, Protocol, TypeVar, Union, runtime_checkable
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

import orjson
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
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
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from openviper.core.context import current_user
from openviper.db.fields import ForeignKey, LazyFK
from openviper.db.models import Q, build_keyset_q, cursor_decode, cursor_encode
from openviper.exceptions import DoesNotExist, PermissionDenied, ValidationError
from openviper.storage import default_storage
from openviper.storage.base import generate_unique_name

# 1 MiB cap prevents memory-exhaustion via oversized JSON payloads.
MAX_JSON_STRING_BYTES: int = 1024 * 1024

# Null bytes, path separators, and control characters that
# could enable injection attacks in uploaded filenames.
UNSAFE_FILENAME_CHAR_RE = re.compile(r"[\x00-\x1f\\/]")

# Schemes permitted for pagination base_url to block open redirects.
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"", "http", "https"})


def encode_next_cursor(last_obj: Any, order_fields: list[str]) -> str | None:
    """Build a keyset cursor from the last object in a page.

    Returns ``None`` when *order_fields* is empty.
    """
    if not order_fields:
        return None
    return cursor_encode(
        {f.lstrip("-"): getattr(last_obj, f.lstrip("-"), None) for f in order_fields}
    )


T = TypeVar("T", bound="Serializer")

logger: logging.Logger = logging.getLogger("openviper.serializers")

field_validator = pydantic_field_validator
model_validator = pydantic_model_validator
computed_field = pydantic_computed_field


def sync_pydantic_state(
    target: BaseModel, source: BaseModel, context: dict[str, Any] | None = None
) -> None:
    """Copy Pydantic internal state from *source* onto *target*.

    Synchronises ``__dict__``, ``__pydantic_fields_set__``,
    ``__pydantic_extra__``, and ``__pydantic_private__`` so that
    *target* behaves as if it were the validated instance.
    """
    object.__setattr__(target, "__dict__", dict(source.__dict__))
    object.__setattr__(target, "__pydantic_fields_set__", source.model_fields_set)
    object.__setattr__(
        target,
        "__pydantic_extra__",
        getattr(source, "__pydantic_extra__", None),
    )
    object.__setattr__(
        target,
        "__pydantic_private__",
        getattr(source, "__pydantic_private__", None),
    )
    if context is not None:
        object.__setattr__(target, "context_data", context)


@runtime_checkable
class OrmModelProtocol(Protocol):
    """Minimal interface that OpenViper ORM models satisfy."""

    _fields: ClassVar[dict[str, Any]]
    _table_name: ClassVar[str]
    id: int
    __dict__: dict[str, Any]

    def __getattr__(self, name: str) -> Any: ...


@runtime_checkable
class OrmManagerProtocol(Protocol):
    """Interface for the ``objects`` manager on ORM models."""

    async def create(self, **kwargs: Any) -> OrmModelProtocol: ...
    async def get(self, **kwargs: Any) -> OrmModelProtocol: ...
    async def get_or_none(self, **kwargs: Any) -> OrmModelProtocol | None: ...


@runtime_checkable
class QuerySetProtocol(Protocol):
    """Interface for lazy chainable query builders."""

    _order: list[str]

    def filter(self, *args: Any, **kwargs: Any) -> QuerySetProtocol: ...
    def offset(self, n: int) -> QuerySetProtocol: ...
    def limit(self, n: int) -> QuerySetProtocol: ...
    async def all(self) -> list[OrmModelProtocol]: ...
    async def count(self) -> int: ...
    async def batch(self, size: int = 100) -> typing.AsyncIterator[list[OrmModelProtocol]]: ...


@runtime_checkable
class OrmFieldProtocol(Protocol):
    """Minimal interface that OpenViper ORM field descriptors satisfy."""

    primary_key: bool
    null: bool
    auto_now: bool
    auto_now_add: bool
    default: Any
    column_name: str
    name: str

    def validate(self, value: Any) -> None: ...
    def has_default(self) -> bool: ...


@runtime_checkable
class RequestProtocol(Protocol):
    """Minimal interface for HTTP request objects."""

    method: str
    path: str

    def __getattr__(self, name: str) -> Any: ...


@runtime_checkable
class PermissionProtocol(Protocol):
    """Interface for permission classes applied to serializers."""

    async def has_permission(self, request: RequestProtocol, serializer: Serializer) -> bool: ...


@runtime_checkable
class UploadValueProtocol(Protocol):
    """Interface for uploaded file values processed by serializers."""

    filename: str
    name: str

    def read(self, size: int = -1) -> bytes: ...
    def __getattr__(self, name: str) -> Any: ...


def map_pydantic_errors(exc: PydanticValidationError) -> ValidationError:
    """Convert a PydanticValidationError to an OpenViper ValidationError."""
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


def map_constraint_error(
    pattern: str, detail: str, column_to_field: dict[str, str], message: str, error_type: str
) -> ValidationError | None:
    """Match *pattern* against *detail*, map the captured column to a field name.

    Returns a :class:`ValidationError` on match, or ``None``.
    """
    match = re.search(pattern, detail)
    if match is None:
        return None
    column = match.group(1)
    field_name = column_to_field.get(column, column)
    return ValidationError(errors=[{"field": field_name, "message": message, "type": error_type}])


class SerializerValidationDescriptor:
    """Expose class-level and staged instance validation through one API."""

    def __get__(self, instance: Serializer | None, owner: type[T]) -> typing.Callable[..., T]:
        if instance is None:
            return owner.validate_data  # type: ignore[return-value]

        def validate_instance(
            *,
            partial: bool = False,
            context: dict[str, Any] | None = None,
            raise_exception: bool = False,
        ) -> Serializer:
            pending_data = getattr(instance, "pending_data", None)
            source_data = pending_data if pending_data is not None else instance.model_dump()
            validation_context = context if context is not None else instance.context_data
            try:
                validated = owner.validate_data(
                    source_data,
                    partial=partial,
                    context=validation_context,
                )
            except ValidationError:
                if raise_exception:
                    raise
                raise
            sync_pydantic_state(instance, validated, validation_context or {})
            object.__setattr__(instance, "pending_data", None)
            return instance

        return validate_instance


# Cache for dynamically-built partial classes.
PARTIAL_CLASSES: WeakKeyDictionary[type, type] = WeakKeyDictionary()


class Serializer(BaseModel):
    """Base serializer backed by :class:`pydantic.BaseModel`.

    Raises :class:`~openviper.exceptions.ValidationError` instead of
    the Pydantic variant on validation failure.
    """

    model_config = ConfigDict(
        from_attributes=True,  # enables ORM mode
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    readonly_fields: ClassVar[tuple[str, ...]] = ()
    writeonly_fields: ClassVar[tuple[str, ...]] = ()
    PAGE_SIZE: ClassVar[int] = 25
    MAX_PAGE_SIZE: ClassVar[int] = 1000
    permission_classes: ClassVar[list[type[PermissionProtocol]]] = []
    validate: ClassVar[SerializerValidationDescriptor] = SerializerValidationDescriptor()

    def __init__(self, **data: Any) -> None:
        context = data.pop("context_data", {})
        if set(data) == {"data"}:
            staged = type(self).model_construct()
            sync_pydantic_state(self, staged)
            object.__setattr__(self, "context_data", context)
            object.__setattr__(self, "pending_data", data["data"])
            return
        super().__init__(**data)
        object.__setattr__(self, "context_data", context)
        object.__setattr__(self, "pending_data", None)

    @property
    def context(self) -> dict[str, Any]:
        return getattr(self, "context_data", {})

    @property
    def validated_data(self) -> dict[str, Any]:
        """Return validated in-memory field values before persistence."""
        if getattr(self, "pending_data", None) is not None:
            raise RuntimeError("Call validate() before accessing validated_data.")
        return self.model_dump(exclude_unset=True)

    async def check_permissions(self) -> None:
        """Evaluate all ``permission_classes`` against the current request.

        Raises :class:`~openviper.exceptions.PermissionDenied` on the
        first failing permission.  Returns immediately when no request
        is bound and no ambient user is present.
        """
        request: RequestProtocol | None = self.context.get("request")
        if request is None and current_user.get() is None:
            return

        for permission_class in self.permission_classes:
            permission = permission_class()
            if not await permission.has_permission(request, self):
                self.permission_denied(request)

    def permission_denied(self, request: RequestProtocol, message: str | None = None) -> None:
        """Raise :class:`~openviper.exceptions.PermissionDenied`."""
        raise PermissionDenied(message or "Permission denied.")

    @classmethod
    def get_excluded_fields(cls, exclude: set[str] | None = None) -> frozenset[str]:
        """Return ``writeonly_fields`` merged with *exclude*."""
        if not cls.writeonly_fields and not exclude:
            return frozenset()
        result = set(cls.writeonly_fields)
        if exclude:
            result |= exclude
        return frozenset(result)

    @staticmethod
    def serialize_value(
        value: (
            bool
            | int
            | float
            | str
            | bytes
            | bytearray
            | memoryview
            | Decimal
            | datetime.datetime
            | datetime.date
            | datetime.time
            | uuid.UUID
            | LazyFK
            | list[Any]
            | dict[str, Any]
            | None
        ),
    ) -> bool | int | float | str | list[Any] | dict[str, Any] | None:
        """Convert a value to a JSON-serializable type.

        Handles Decimal, datetime, date, time, UUID, bytes, and
        other non-JSON-serializable types common in ORM fields.
        Arbitrary binary data is represented as base64 to avoid
        leaking raw bytes through encoding fallbacks.
        """
        if value is None:
            return None
        if isinstance(value, LazyFK):
            return value.fk_id
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, bytes):
            return base64.b64encode(value).decode("ascii")
        if isinstance(value, (list, tuple)):
            return [Serializer.serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: Serializer.serialize_value(v) for k, v in value.items()}
        return value

    @classmethod
    def obj_to_dict(cls, obj: OrmModelProtocol, excl: frozenset[str]) -> dict[str, Any]:
        """Map a single ORM object to a JSON-safe dict."""
        return {
            fname: cls.serialize_value(getattr(obj, fname, None))
            for fname in cls.model_fields  # pylint: disable=not-an-iterable
            if fname not in excl
        }

    @classmethod
    def build_partial_class(cls: type[T]) -> type[T]:
        """Return a version of this class where every field is optional.

        The result is cached on ``PARTIAL_CLASSES`` so it is only
        created once per serializer class.  The returned class tracks
        which fields were actually supplied via ``model_fields_set``;
        callers can therefore use ``model_dump(exclude_unset=True)``
        to apply only the provided values (see :meth:`update`).
        """
        cached = PARTIAL_CLASSES.get(cls)
        if cached is not None:
            return cached  # type: ignore[return-value]

        fields_spec: dict[str, tuple[Any, Any]] = {}
        for fname, fi in cls.model_fields.items():
            ann = fi.annotation
            origin = typing.get_origin(ann)
            args = typing.get_args(ann)
            already_optional = origin is Union and type(None) in args
            new_ann = ann if already_optional else ann | None

            new_fi = copy(fi)
            new_fi.default = None
            fields_spec[fname] = (new_ann, new_fi)

        partial_cls: type[T] = create_model(
            f"Partial{cls.__name__}",
            __base__=cls,
            __config__=ConfigDict(
                from_attributes=True,
                populate_by_name=True,
                validate_default=False,
                arbitrary_types_allowed=True,
            ),
            **fields_spec,
        )
        after_validators = {
            name: dec
            for name, dec in partial_cls.__pydantic_decorators__.model_validators.items()
            if dec.info.mode == "after"
        }
        for name in after_validators:
            partial_cls.__pydantic_decorators__.model_validators.pop(name, None)
        PARTIAL_CLASSES[cls] = partial_cls
        return partial_cls

    @classmethod
    def validate_data(
        cls: type[T],
        data: dict[str, Any] | OrmModelProtocol | typing.Mapping[str, Any],
        *,
        partial: bool = False,
        context: dict[str, Any] | None = None,
    ) -> T:
        """Parse *data* into this serializer.

        Raises :class:`~openviper.exceptions.ValidationError`.

        Args:
            data: Dict, ORM object, or any mapping accepted by Pydantic.
            partial: When ``True`` every field becomes optional.
                The returned instance records which fields were supplied
                via ``model_fields_set``; pass
                ``model_dump(exclude_unset=True)`` to :meth:`update` when
                only the changed keys should be written.
            context: Optional dictionary of extra context.
        """
        target = cls.build_partial_class() if partial else cls
        try:
            instance = target.model_validate(data, context=context)
        except PydanticValidationError as exc:
            raise map_pydantic_errors(exc) from exc
        object.__setattr__(instance, "context_data", context or {})
        return instance  # type: ignore[return-value]

    @classmethod
    def validate_json_string(cls: type[T], json_str: str) -> T:
        """Parse a raw JSON string.

        Raises :class:`~openviper.exceptions.ValidationError` if
        the input exceeds ``MAX_JSON_STRING_BYTES``.
        """
        if len(json_str) > MAX_JSON_STRING_BYTES:
            raise ValidationError(
                errors=[
                    {
                        "field": "__all__",
                        "message": (
                            f"JSON input exceeds maximum allowed size"
                            f" of {MAX_JSON_STRING_BYTES} bytes."
                        ),
                        "type": "value_error",
                    }
                ]
            )
        try:
            return cls.model_validate_json(json_str)
        except PydanticValidationError as exc:
            raise map_pydantic_errors(exc) from exc

    @classmethod
    def from_orm(cls: type[T], obj: OrmModelProtocol) -> T:
        """Construct from an ORM object (requires
        ``from_attributes=True``).
        """
        orm_fields: dict[str, Any] = getattr(obj.__class__, "_fields", {})
        if not orm_fields:
            return cls.model_validate(obj)
        data: dict[str, Any] = {}
        for fname in cls.model_fields:  # pylint: disable=not-an-iterable
            orm_field = orm_fields.get(fname)
            if isinstance(orm_field, ForeignKey):
                # Descriptor coercion can mangle None → 0; read
                # __dict__ directly and fall back to getattr for
                # lazy-loaded proxies.
                col = orm_field.column_name
                fk_val = obj.__dict__[col] if col in obj.__dict__ else getattr(obj, col, None)
                # Unwrap model instances to their primary key.
                if fk_val is not None and hasattr(fk_val, "id"):
                    fk_val = getattr(fk_val, "id", None)
                data[fname] = fk_val
            else:
                data[fname] = getattr(obj, fname, None)
        return cls.model_validate(data)

    @classmethod
    def from_orm_many(cls: type[T], objs: list[OrmModelProtocol]) -> list[T]:
        """Construct a list of serializer instances from ORM objects."""
        return [cls.from_orm(obj) for obj in objs]

    def compute_excluded(self, exclude: set[str] | None) -> set[str] | None:
        """Return ``writeonly_fields`` merged with *exclude*."""
        result = self.get_excluded_fields(exclude)
        return set(result) if result else None

    def serialize(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Return a JSON-safe dict, automatically excluding write-only fields."""
        return self.model_dump(mode="json", exclude=self.compute_excluded(exclude))

    @classmethod
    async def serialize_many(
        cls: type[T],
        objs: QuerySetProtocol | list[OrmModelProtocol],
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Serialize a list or QuerySet of ORM objects to dicts.

        QuerySets are fetched in ``PAGE_SIZE``-sized batches to
        avoid loading the entire result set into memory.
        """
        results = await cls.collect_dicts(objs, exclude=exclude)
        return results

    def serialize_json(self, *, exclude: set[str] | None = None) -> bytes:
        """Return JSON bytes via pydantic-core's Rust encoder."""
        return self.model_dump_json(exclude=self.compute_excluded(exclude)).encode()

    @classmethod
    async def collect_dicts(
        cls: type[T],
        objs: QuerySetProtocol | list[OrmModelProtocol],
        *,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect ORM objects into JSON-safe dicts, batching QuerySets.

        Shared implementation for :meth:`serialize_many` and
        :meth:`serialize_many_json`.
        """
        excl = cls.get_excluded_fields(exclude)

        if hasattr(objs, "batch"):
            results: list[dict[str, Any]] = []
            async for batch in objs.batch(size=cls.PAGE_SIZE):
                results.extend(cls.obj_to_dict(obj, excl) for obj in batch)
            return results

        return [cls.obj_to_dict(obj, excl) for obj in objs]

    @classmethod
    async def serialize_many_json(
        cls: type[T],
        objs: QuerySetProtocol | list[OrmModelProtocol],
        *,
        exclude: set[str] | None = None,
    ) -> bytes:
        """Serialize a list or QuerySet of ORM objects to JSON bytes.

        QuerySets are fetched in ``PAGE_SIZE``-sized batches.
        """
        results = await cls.collect_dicts(objs, exclude=exclude)
        return orjson.dumps(results)

    @classmethod
    async def paginate(
        cls: type[T],
        qs: QuerySetProtocol,
        *,
        page: int = 1,
        page_size: int | None = None,
        cursor: str | None = None,
        base_url: str = "",
        exclude: set[str] | None = None,
    ) -> PaginatedSerializer:
        """Return a :class:`PaginatedSerializer` for a single page.

        Keyset pagination (via *cursor*) seeks directly to the
        cursor position at O(log N) regardless of page depth.
        When *cursor* is omitted, falls back to OFFSET-based
        pagination.

        Args:
            qs: A QuerySet.
            page: 1-based page number (OFFSET mode only).
            page_size: Items per page.  Defaults to
                ``cls.PAGE_SIZE`` (25).
            cursor: Opaque keyset cursor from a previous
                response.
            base_url: When provided, ``next`` / ``previous``
                URLs are built.
            exclude: Field names to omit from each item.

        Returns:
            A :class:`PaginatedSerializer` with ``count``,
            ``next``, ``previous``, ``results``, and optionally
            ``next_cursor``.
        """
        # Mitigate open redirect injection via base_url.
        if base_url:
            parsed_base = urlparse(base_url)
            if parsed_base.scheme and parsed_base.scheme not in ALLOWED_URL_SCHEMES:
                base_url = ""
            if parsed_base.netloc:
                # Absolute URLs with netloc are external redirects.
                base_url = ""

        if isinstance(qs, list):
            raise TypeError(
                "paginate() expects a QuerySet, not a list. "
                "Remove .all() from the queryset before passing it to paginate()."
            )

        ps = page_size if page_size is not None else cls.PAGE_SIZE
        ps = max(1, min(ps, cls.MAX_PAGE_SIZE))
        page = max(1, page)

        excl = cls.get_excluded_fields(exclude)
        order_fields = list(getattr(qs, "_order", []))

        if cursor is not None:
            # Keyset path: O(log N) with no OFFSET.
            cursor_values = cursor_decode(cursor)
            keyset_q: Q | None = (
                build_keyset_q(order_fields, cursor_values)
                if cursor_values and order_fields
                else None
            )
            page_qs = qs.filter(keyset_q) if keyset_q is not None else qs

            total, objs = await asyncio.gather(
                qs.count(),
                page_qs.limit(ps).all(),
            )

            next_cur: str | None = (
                encode_next_cursor(objs[-1], order_fields) if len(objs) == ps else None
            )

            next_url: str | None = (
                f"{base_url}?cursor={next_cur}&page_size={ps}" if base_url and next_cur else None
            )

            results = [cls.obj_to_dict(obj, excl) for obj in objs]
            return PaginatedSerializer(
                count=total,
                next=next_url,
                previous=None,
                results=results,
                next_cursor=next_cur,
            )

        # OFFSET path: first uncursored request only.
        offset = (page - 1) * ps
        page_qs = qs.offset(offset).limit(ps)

        total, objs = await asyncio.gather(
            qs.count(),
            page_qs.all(),
        )

        # Encode a cursor from the last item so subsequent
        # requests use keyset pagination.
        next_cur_offset: str | None = (
            encode_next_cursor(objs[-1], order_fields) if len(objs) == ps else None
        )

        next_url = None
        prev_url = None
        if base_url:
            # Prefer cursor for faster keyset navigation.
            if next_cur_offset and offset + ps < total:
                next_url = f"{base_url}?cursor={next_cur_offset}&page_size={ps}"
            elif offset + ps < total:
                next_url = f"{base_url}?page={page + 1}&page_size={ps}"
            if page > 1:
                prev_url = f"{base_url}?page={page - 1}&page_size={ps}"

        results = [cls.obj_to_dict(obj, excl) for obj in objs]

        return PaginatedSerializer(
            count=total,
            next=next_url,
            previous=prev_url,
            results=results,
            next_cursor=next_cur_offset,
        )


FIELD_TYPE_MAP: dict[str, type] = {
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

FILE_FIELD_TYPES: frozenset[str] = frozenset({"FileField", "ImageField"})


@lru_cache(maxsize=256)
def python_type_for_field_by_name(field_class_name: str) -> type:
    """Return the Python type for an ORM field class name."""
    return FIELD_TYPE_MAP.get(field_class_name, Any)


@lru_cache(maxsize=256)
def field_is_optional_cached(
    primary_key: bool,
    null: bool,
    auto_now: bool,
    auto_now_add: bool,
    has_default: bool,
) -> bool:
    """Return ``True`` if a field with these attributes is optional."""
    if primary_key:
        return True  # PK is auto-generated
    if null:
        return True
    if auto_now or auto_now_add:
        return True
    return has_default


def field_is_optional(field: OrmFieldProtocol) -> bool:
    """Return ``True`` if the field allows ``None``."""
    # ``None`` means "no default set" in OpenViper's field API,
    # NOT the Python value None.  Detect a real default via
    # ``has_default()`` first, then fall back to comparing
    # against the ``NOT_PROVIDED`` sentinel on the field class.
    raw_default = getattr(field, "default", None)
    not_provided = getattr(type(field), "NOT_PROVIDED", None)
    if not_provided is not None:
        has_default = raw_default is not not_provided
    else:
        # Treat any value (including False, 0, "") as having a
        # default; only Python None means "no default".
        has_default = raw_default is not None or getattr(field, "has_default", lambda: False)()
    return field_is_optional_cached(
        primary_key=getattr(field, "primary_key", False),
        null=getattr(field, "null", False),
        auto_now=getattr(field, "auto_now", False),
        auto_now_add=getattr(field, "auto_now_add", False),
        has_default=has_default,
    )


class ModelSerializerMeta(type(BaseModel)):
    """Metaclass for :class:`ModelSerializer`.

    Reads ``Meta.model`` / ``Meta.fields`` / ``Meta.exclude`` at
    class-creation time and builds Pydantic ``model_fields``.
    """

    def __new__(  # pylint: disable=bad-classmethod-argument
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> ModelSerializerMeta:
        meta = namespace.get("Meta")
        model = getattr(meta, "model", None) if meta else None

        if model is None:
            return super().__new__(mcs, name, bases, namespace, **kwargs)

        fields_opt: str | list[str] = getattr(meta, "fields", "__all__")
        exclude_opt: list[str] | tuple[str, ...] = getattr(meta, "exclude", ())
        read_only: tuple[str, ...] = getattr(meta, "readonly_fields", ())
        write_only: tuple[str, ...] = getattr(meta, "writeonly_fields", ())
        extra_kwargs: dict[str, dict[str, Any]] = getattr(meta, "extra_kwargs", {})

        model_fields: dict[str, Any] = getattr(model, "_fields", {})

        exclude_set = frozenset(exclude_opt)
        field_names = list(model_fields.keys()) if fields_opt == "__all__" else list(fields_opt)
        field_names = [f for f in field_names if f not in exclude_set]

        annotations: dict[str, Any] = namespace.get("__annotations__", {})
        # Keys excluded from pydantic.Field().
        serializer_only_keys: frozenset[str] = frozenset({"required"})

        for field_name in field_names:
            if field_name in annotations or field_name in namespace:
                continue

            orm_field = model_fields.get(field_name)
            if orm_field is None:
                continue

            field_class_name = type(orm_field).__name__
            py_type = python_type_for_field_by_name(field_class_name)
            optional = field_is_optional(orm_field)

            field_extra = extra_kwargs.get(field_name, {})
            if field_extra.get("required") is False:
                optional = True

            pydantic_field_kwargs = {
                k: v for k, v in field_extra.items() if k not in serializer_only_keys
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

        cls.model_class = model  # type: ignore[attr-defined]

        return cls


class ModelSerializer(Serializer, metaclass=ModelSerializerMeta):
    """Serializer with fields auto-derived from a OpenViper :class:`~openviper.db.models.Model`.

    Requires an inner ``Meta`` class defining at minimum ``model``
    and ``fields``.  Supports ``exclude``, ``readonly_fields``,
    ``writeonly_fields``, and ``extra_kwargs``.
    """

    model_class: ClassVar[type]

    @classmethod
    def get_model_fields(cls) -> dict[str, Any]:
        """Return the ORM field mapping from the associated model class."""
        return getattr(cls.model_class, "_fields", {})

    @classmethod
    @lru_cache(maxsize=512)
    def get_file_fields(cls) -> MappingProxyType:
        """Return a read-only mapping of file-type ORM fields.

        Cached with LRU eviction.  The returned
        ``MappingProxyType`` prevents cache mutation.
        """
        model_fields = cls.get_model_fields()
        file_fields = {
            name: field
            for name, field in model_fields.items()
            if type(field).__name__ in FILE_FIELD_TYPES
        }
        return MappingProxyType(file_fields)

    @classmethod
    def validate_file_sizes(cls, data: dict[str, Any]) -> None:
        """Raise :class:`~openviper.exceptions.ValidationError`
        if any file value exceeds its limit.
        """
        file_fields = cls.get_file_fields()
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
    async def persist_files(
        cls,
        data: dict[str, Any],
        *,
        old_instance: OrmModelProtocol | None = None,
    ) -> dict[str, Any]:
        """Save file values through the storage backend.

        Returns a copy of *data* with file values replaced by
        their stored paths.  On update, the previous file is
        deleted from storage after the new one is persisted.
        """
        file_fields = cls.get_file_fields()
        if not file_fields:
            return data

        result = dict(data)

        async def process_file(
            name: str,
            orm_field: OrmFieldProtocol,
            value: UploadValueProtocol | bytes | bytearray | memoryview,
        ) -> tuple[str, str]:
            """Return (field_name, saved_path) after persisting."""
            # Prevent path traversal.
            # Normalize backslashes so basename extraction works
            # on POSIX.
            raw_name = getattr(value, "filename", None) or getattr(value, "name", None) or "file"
            filename = raw_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1] or "file"
            # Reject filenames with null bytes, path separators,
            # or control characters that enable injection.
            if UNSAFE_FILENAME_CHAR_RE.search(filename):
                raise ValidationError(
                    errors=[
                        {
                            "field": name,
                            "message": f"Filename {filename!r} contains unsafe characters.",
                            "type": "value_error",
                        }
                    ]
                )
            upload_to = getattr(orm_field, "upload_to", "uploads/")
            # Sanitize upload_to: strip leading slashes and
            # collapse '..' segments to prevent writing outside
            # the storage root.
            clean_parts = [p for p in upload_to.lstrip("/").split("/") if p not in ("", ".", "..")]
            clean_upload_to = "/".join(clean_parts) if clean_parts else "uploads"
            target_name = generate_unique_name(f"{clean_upload_to}/{filename}")

            if isinstance(value, bytes):
                content: bytes | typing.IO[bytes] = value
            elif hasattr(value, "read"):
                # Stream file-like objects without buffering.
                content = value
            elif isinstance(value, (bytearray, memoryview)):
                content = bytes(value)
            else:
                raise TypeError(f"Unsupported file value type: {type(value).__name__}")

            saved_path = await default_storage.save(target_name, content)

            # Delete old file only after new one is persisted.
            if old_instance is not None:
                old_path = getattr(old_instance, name, None)
                if old_path and isinstance(old_path, str):
                    try:
                        await default_storage.delete(old_path)
                    except Exception as exc:
                        logger.warning(
                            "Failed to delete old file %s: %s",
                            old_path,
                            exc,
                        )
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

    @classmethod
    def validate_create_data(cls, data: dict[str, Any]) -> None:
        """Reject creates that cannot satisfy required model fields."""
        errors: list[dict[str, str]] = []
        model_fields = cls.get_model_fields()
        for field_name, field in model_fields.items():
            if field_is_optional(field) or field_name in data:
                continue
            message = (
                "Required field is read-only and cannot be saved."
                if field_name in cls.readonly_fields
                else "Required field is missing."
            )
            errors.append(
                {
                    "field": field_name,
                    "message": message,
                    "type": "missing",
                }
            )
        if errors:
            raise ValidationError(errors=errors)

    @classmethod
    def integrity_error_to_validation_error(
        cls,
        exc: SQLAlchemyIntegrityError,
    ) -> ValidationError:
        """Map database integrity failures to serializer errors."""
        detail = str(exc.orig) if getattr(exc, "orig", None) is not None else str(exc)
        column_to_field = {
            getattr(field, "column_name", field_name): field_name
            for field_name, field in cls.get_model_fields().items()
        }

        unique_err = map_constraint_error(
            r"UNIQUE constraint failed: \w+\.(\w+)",
            detail,
            column_to_field,
            "This value must be unique.",
            "unique",
        )
        if unique_err is not None:
            return unique_err

        not_null_err = map_constraint_error(
            r"NOT NULL constraint failed: \w+\.(\w+)",
            detail,
            column_to_field,
            "This field is required.",
            "missing",
        )
        if not_null_err is not None:
            return not_null_err

        return ValidationError(
            errors=[
                {
                    "field": "__all__",
                    "message": "Database integrity constraint failed.",
                    "type": "integrity_error",
                }
            ]
        )

    def extract_writable_data(
        self, *, exclude_mode: str = "none", drop_id: bool = False
    ) -> dict[str, Any]:
        """Return a dict of serializer fields safe for persistence.

        Strips write-only fields, read-only fields, and (optionally) the
        primary key.  *exclude_mode* is forwarded to
        ``model_dump``: ``"none"`` uses ``exclude_none=True`` (for
        create), ``"unset"`` uses ``exclude_unset=True`` (for update).
        """
        allowed_keys = set(type(self).model_fields) - set(self.writeonly_fields)
        if exclude_mode == "unset":
            data = {
                k: v for k, v in self.model_dump(exclude_unset=True).items() if k in allowed_keys
            }
        else:
            data = {
                k: v for k, v in self.model_dump(exclude_none=True).items() if k in allowed_keys
            }
        for f in self.readonly_fields:
            data.pop(f, None)
        if drop_id:
            data.pop("id", None)
        return data

    async def create(self) -> OrmModelProtocol:
        """Persist a new model instance from the validated data.

        Only serializer-declared fields are forwarded to the ORM.
        Read-only and write-only fields are stripped.
        """
        await self.check_permissions()
        data = self.extract_writable_data(exclude_mode="none")
        # Drop an explicit None pk so the DB generates the value.
        pk_val = data.get("id")
        if pk_val is None:
            data.pop("id", None)

        self.validate_create_data(data)
        self.validate_file_sizes(data)
        data = await self.persist_files(data)

        try:
            return await self.model_class.objects.create(**data)
        except SQLAlchemyIntegrityError as exc:
            raise self.integrity_error_to_validation_error(exc) from exc

    async def update(self, instance: OrmModelProtocol) -> OrmModelProtocol:
        """Apply validated data to an existing *instance* and save.

        Only serializer-declared fields explicitly set by the client
        are forwarded.  Read-only fields and the primary key are
        always stripped.
        """
        await self.check_permissions()
        data = self.extract_writable_data(exclude_mode="unset", drop_id=True)

        self.validate_file_sizes(data)
        data = await self.persist_files(data, old_instance=instance)

        for attr, value in data.items():
            setattr(instance, attr, value)
        try:
            await instance.save()
        except SQLAlchemyIntegrityError as exc:
            raise self.integrity_error_to_validation_error(exc) from exc
        return instance

    async def save(self, instance: OrmModelProtocol | None = None) -> dict[str, Any]:
        """Create or update a model instance and return serialized data.

        If *instance* is provided, update it.  If the validated
        data contains a non-``None`` ``id`` / ``pk``, fetch the
        existing record and update it.  Otherwise create a new
        record.

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
                existing = await self.model_class.objects.get(id=pk_value)
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
    results: list[dict[str, Any]]
    next_cursor: str | None = None
