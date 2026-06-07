"""OpenViper ORM - Model base classes, fields, and query API.

Built on top of SQLAlchemy Core for cross-database support with an
ergonomic high-level API.

Example:
    .. code-block:: python

        from openviper.db.models import Model
        from openviper.db import fields

        class Post(Model):
            class Meta:
                table_name = "posts"

            title = fields.CharField(max_length=255)
            body  = fields.TextField()
            created_at = fields.DateTimeField(auto_now_add=True)

        # Query
        posts = await Post.objects.filter(title__contains="OpenViper").all()
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import decimal
import functools
import inspect
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, cast

import sqlalchemy as sa
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from openviper.auth.permission_core import (
    AuthPermissionError as ModelPermissionError,
)
from openviper.auth.permission_core import (
    check_permission_for_model,
)
from openviper.core.context import ignore_permissions_ctx
from openviper.db import _model_registry as registry_mod
from openviper.db._traversal import TraversalLookup, TraversalStep
from openviper.db.backends.registry import backend_registry
from openviper.db.events import dispatch_decorator_handlers, get_dispatcher
from openviper.db.exceptions import (
    ReadOnlyVirtualModelError,
    SingleModelAlreadyExistsError,
    SingleModelDeleteForbiddenError,
    SingleModelDoesNotExist,
    UnsupportedVirtualQueryError,
)
from openviper.db.executor import (
    begin,
    execute_aggregate,
    execute_bulk_update,
    execute_count,
    execute_delete,
    execute_delete_instance,
    execute_exists,
    execute_explain,
    execute_save,
    execute_select,
    execute_update,
    execute_values,
    get_soft_removed_columns,
    get_table,
    load_soft_removed_columns,
)
from openviper.db.fields import (
    Constraint,
    DateTimeField,
    Field,
    ForeignKey,
    IntegerField,
    LazyFK,
    ManyToManyDescriptor,
    ManyToManyField,
    ManyToManyManager,
    ReverseRelationDescriptor,
)
from openviper.db.queryspec import FilterClause, FilterOp, QuerySpec
from openviper.db.utils import enforce_single_model_constraint, validate_sql_expression
from openviper.exceptions import DoesNotExist, FieldError, MultipleObjectsReturned
from openviper.utils import timezone

T = TypeVar("T", bound="Model")

if TYPE_CHECKING:
    from openviper.db.backends.base import VirtualBackend


class ClassProperty:
    """Descriptor that exposes a method as a read-only class-level property."""

    def __init__(self, func: Any) -> None:
        self.func = func

    def __get__(self, instance: Any, owner: type[Any]) -> Any:
        return self.func(owner)


# Pre-compiling avoids re-compilation overhead on every model class creation.
_CAMEL_RE1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE2 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_RE3 = re.compile(r"(?<!^)(?=[A-Z])")

# Caching per request avoids redundant permission queries within the same async context.
_perm_cache: ContextVar[dict[tuple[type, str], bool] | None] = ContextVar(
    "_perm_cache", default=None
)

logger = logging.getLogger(__name__)


async def check_perm_cached(model: type, action: str, ignore_permissions: bool = False) -> None:
    """Check permissions with per-request caching.

    Once a (model, action) pair has been checked successfully within a
    request, subsequent calls return immediately without re-checking.
    """
    if ignore_permissions:
        return

    cache = _perm_cache.get()
    if cache is None:
        # Without a request context the per-request cache cannot be used;
        # fall through to the uncached check.
        await check_permission_for_model(model, action, ignore_permissions=False)
        return

    key = (model, action)
    if key in cache:
        return  # Already verified this request.

    await check_permission_for_model(model, action, ignore_permissions=False)
    cache[key] = True


# -- Model Options -------------------------------------------------------------


class ModelOptions:
    """Metadata container for a Model class.

    Aggregates all Meta-level configuration into a single object accessible
    via ``cls._meta``.  This mirrors Django's ``Options`` pattern and
    provides a clean interface for introspecting model configuration
    without reaching for scattered private class attributes.
    """

    __slots__ = (
        "table_name",
        "app_name",
        "model_name",
        "verbose_name",
        "verbose_name_plural",
        "ordering",
        "abstract",
        "proxy",
        "managed",
        "virtual",
        "backend",
        "read_only",
        "single",
        "cache_ttl",
    )

    def __init__(
        self,
        table_name: str,
        app_name: str,
        model_name: str,
        verbose_name: str,
        verbose_name_plural: str,
        ordering: list[str],
        abstract: bool,
        proxy: bool,
        managed: bool,
        virtual: bool,
        backend: str,
        read_only: bool,
        single: bool,
        cache_ttl: int,
    ) -> None:
        self.table_name = table_name
        self.app_name = app_name
        self.model_name = model_name
        self.verbose_name = verbose_name
        self.verbose_name_plural = verbose_name_plural
        self.ordering = ordering
        self.abstract = abstract
        self.proxy = proxy
        self.managed = managed
        self.virtual = virtual
        self.backend = backend
        self.read_only = read_only
        self.single = single
        self.cache_ttl = cache_ttl

    def __repr__(self) -> str:
        return (
            f"<ModelOptions table={self.table_name!r} "
            f"virtual={self.virtual} backend={self.backend!r}>"
        )


# -- Metaclass -----------------------------------------------------------------


class ModelMeta(type):
    """Metaclass that collects field definitions and wires up the Manager.

    Automatically generates table_name as {app_name}_{model_name} in snake_case
    if not explicitly specified in Meta.table_name.
    """

    # Share the registry dict with _model_registry so fields.py and
    # executor.py can access it without importing models.py (circular dep).
    registry: ClassVar[dict[str, type[Model]]] = registry_mod.registry
    name_index: ClassVar[dict[str, list[type]]] = registry_mod.name_index
    # FK targets may not be registered yet; defer reverse wiring until the target class appears.
    _pending_reverse_wirings: ClassVar[list[tuple[type, str, ForeignKey]]] = []

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ModelMeta:
        fields: dict[str, Field] = {}

        for base in bases:
            if hasattr(base, "_fields"):
                fields.update(base._fields)

        for attr_name, attr_val in list(namespace.items()):
            if isinstance(attr_val, Field):
                attr_val.name = attr_name
                fields[attr_name] = attr_val
                # Expose the FK column_name (e.g. user_id) as an attribute
                # so hasattr() works without descriptor access.
                if hasattr(attr_val, "column_name") and attr_val.column_name != attr_name:
                    namespace[attr_val.column_name] = attr_val

        namespace["_fields"] = fields

        app_name = mcs._extract_app_name(namespace.get("__module__", ""), name)
        namespace["_app_name"] = app_name
        namespace["_model_name"] = name

        # Explicit table_name overrides convention; auto-generation
        # ensures consistent naming across apps.
        meta = namespace.get("Meta")
        table_name = ""
        is_abstract = False
        is_proxy = False
        is_managed = True
        is_virtual = False
        backend_name = "default"
        is_read_only = False
        is_single = False
        meta_indexes: list[Index] = []
        meta_unique_together: list[list[str]] = []
        meta_constraints: list[Constraint] = []
        verbose_name: str | None = None
        verbose_name_plural: str | None = None
        ordering: list[str] = []

        if meta:
            is_abstract = getattr(meta, "abstract", False)
            is_proxy = getattr(meta, "proxy", False)
            is_managed = getattr(meta, "managed", True)
            is_virtual = getattr(meta, "virtual", False)
            backend_name = getattr(meta, "backend", "default")
            is_read_only = getattr(meta, "read_only", False)
            is_single = getattr(meta, "single", False)
            if hasattr(meta, "table_name") and meta.table_name:
                table_name = meta.table_name

            # Meta.virtual must be a strict boolean to avoid truthy coercion bugs.
            if not isinstance(is_virtual, bool):
                raise FieldError(f"Meta.virtual must be a boolean, got {type(is_virtual).__name__}")
            if not isinstance(is_single, bool):
                raise FieldError(f"Meta.single must be a boolean, got {type(is_single).__name__}")

            if hasattr(meta, "indexes"):
                meta_indexes = list(meta.indexes)
            if hasattr(meta, "unique_together"):
                ut = meta.unique_together
                # Normalize both ("f1", "f2") and
                # (("f1",), ("f2", "f3")) into a uniform list-of-lists shape.
                if isinstance(ut, (list, tuple)):
                    if ut and isinstance(ut[0], (list, tuple)):
                        meta_unique_together = [list(item) for item in ut]
                    else:
                        meta_unique_together = [list(ut)]

            if hasattr(meta, "constraints"):
                meta_constraints = list(meta.constraints)

            verbose_name = getattr(meta, "verbose_name", None)
            verbose_name_plural = getattr(meta, "verbose_name_plural", None)
            if hasattr(meta, "ordering"):
                ord_val = meta.ordering
                if isinstance(ord_val, str):
                    ordering = [ord_val]
                elif isinstance(ord_val, (list, tuple)):
                    ordering = list(ord_val)

        # Proxy models share the parent table; auto-generating a name would create an orphan table.
        if is_proxy and not table_name:
            for base in bases:
                if hasattr(base, "_table_name") and base._table_name:
                    table_name = base._table_name
                    break

        if not table_name:
            model_snake = mcs._camel_to_snake(name)
            if app_name and app_name != "default" and name != "Model" and not is_abstract:
                table_name = f"{app_name}_{model_snake}".lower()
            else:
                # Legacy apps without an app_name use pluralized snake_case
                # for backward compatibility.
                table_name = _CAMEL_RE3.sub("_", name).lower() + "s"

        # Index field names must resolve to real fields; fail early to surface migration bugs.
        for idx in meta_indexes:
            for f_name in idx.fields:
                if f_name not in fields:
                    raise FieldError(f"Index field '{f_name}' not found on {name}")

        for ut_fields in meta_unique_together:
            for f_name in ut_fields:
                if f_name not in fields:
                    raise FieldError(f"unique_together field '{f_name}' not found on {name}")

        for f_name in ordering:
            clean_name = f_name[1:] if f_name.startswith("-") else f_name
            if clean_name not in fields:
                raise FieldError(f"Ordering field '{clean_name}' not found on {name}")

        if verbose_name is None:
            verbose_name = name
        if verbose_name_plural is None:
            verbose_name_plural = f"{verbose_name}s"

        namespace["_table_name"] = table_name
        namespace["_is_abstract"] = is_abstract
        namespace["_is_proxy"] = is_proxy
        namespace["_is_managed"] = is_managed
        namespace["_is_virtual"] = is_virtual
        namespace["_backend_name"] = backend_name
        namespace["_is_read_only"] = is_read_only
        namespace["_is_single"] = is_single
        namespace["_meta_indexes"] = meta_indexes
        namespace["_meta_unique_together"] = meta_unique_together
        namespace["_meta_constraints"] = meta_constraints
        namespace["_verbose_name"] = verbose_name
        namespace["_verbose_name_plural"] = verbose_name_plural
        namespace["_ordering"] = ordering
        namespace["_cache_ttl"] = getattr(meta, "cache_ttl", 0) if meta else 0

        cls = super().__new__(mcs, name, bases, namespace)

        # ModelOptions needs the fully-constructed class to resolve field references correctly.
        cls._meta = ModelOptions(
            table_name=table_name,
            app_name=app_name,
            model_name=name,
            verbose_name=verbose_name,
            verbose_name_plural=verbose_name_plural,
            ordering=ordering,
            abstract=is_abstract,
            proxy=is_proxy,
            managed=is_managed,
            virtual=is_virtual,
            backend=backend_name,
            read_only=is_read_only,
            single=is_single,
            cache_ttl=getattr(meta, "cache_ttl", 0) if meta else 0,
        )

        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField) and hasattr(field_obj, "contribute_to_class"):
                field_obj.contribute_to_class(cls, field_name)

        if name != "Model" and not is_abstract:
            manager = Manager(cast("Any", cls))
            cls.objects = manager
            get_table(cast("Any", cls))
            registry_key = f"{app_name}.{name}"
            mcs.registry[registry_key] = cast("Any", cls)
            # A simple-name index enables O(1) resolve_target() lookups
            # without scanning the full registry.
            mcs.name_index.setdefault(name, []).append(cast("Any", cls))

            # FK fields with related_name need reverse accessors on the
            # target model for bidirectional traversal.
            for field_name, field_obj in fields.items():
                if not isinstance(field_obj, ForeignKey) or not field_obj.related_name:
                    continue
                target_cls = field_obj.resolve_target()
                if target_cls is not None:
                    setattr(
                        target_cls,
                        field_obj.related_name,
                        ReverseRelationDescriptor(cast("Any", cls), field_name),
                    )
                else:
                    mcs._pending_reverse_wirings.append(
                        (cast("Any", cls), field_name, cast("Any", field_obj))
                    )

            # A newly registered model may resolve pending FK wirings that
            # previously failed because the target was missing.
            still_pending: list[tuple[type, str, ForeignKey]] = []
            for src_model, fk_fname, fk_field in mcs._pending_reverse_wirings:
                resolved = fk_field.resolve_target()
                if resolved is not None and fk_field.related_name is not None:
                    setattr(
                        resolved,
                        fk_field.related_name,
                        ReverseRelationDescriptor(src_model, fk_fname),
                    )
                else:
                    still_pending.append((src_model, fk_fname, fk_field))
            mcs._pending_reverse_wirings = still_pending

        return cls

    @staticmethod
    def _extract_app_name(module: str, model_name: str) -> str:
        """Extract app name from module path.

        Examples:
            'apps.blog.models' -> 'blog'
            'apps.users.models' -> 'users'
            'openviper.auth.models' -> 'auth'
        """
        if not module:
            return "default"

        parts = module.split(".")

        if "apps" in parts:
            app_index = parts.index("apps")
            if app_index + 1 < len(parts):
                return parts[app_index + 1]

        if "openviper" in parts and len(parts) >= 3:
            return parts[1]  # e.g., 'auth' from 'openviper.auth.models'

        return parts[-2] if len(parts) >= 2 else "default"

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert CamelCase to snake_case.

        Examples:
            'Post' -> 'post'
            'PostView' -> 'post_view'
            'UserFollow' -> 'user_follow'
        """
        s1 = _CAMEL_RE1.sub(r"\1_\2", name)
        return _CAMEL_RE2.sub(r"\1_\2", s1).lower()


class Index:
    """Represents a database index.

    Use in ``Meta.indexes`` to define composite or named indexes.

    The *condition* string is validated against dangerous SQL patterns to
    prevent statement injection in partial-index WHERE clauses.

    Example::

        class User(Model):
            class Meta:
                indexes = [
                    Index(fields=["first_name", "last_name"], name="idx_user_names")
                ]
    """

    __slots__ = ("fields", "name", "condition")

    def __init__(
        self,
        fields: list[str],
        name: str | None = None,
        condition: str | None = None,
    ) -> None:
        if condition is not None:
            validate_sql_expression(condition, "condition", "Index")
        self.fields = fields
        self.name = name
        self.condition = condition

    def __repr__(self) -> str:
        return f"Index(fields={self.fields!r}, name={self.name!r}, condition={self.condition!r})"


# -- F expression -------------------------------------------------------------


class F:
    """Reference a model field for database-side operations.

    Use in ``filter()`` / ``update()`` calls to reference and mutate column
    values without loading them into Python first.

    Supports arithmetic operators: ``+``, ``-``, ``*``, ``/``::

        # Atomic increment without a round-trip
        await Post.objects.filter(pk=1).update(views=F("views") + 1)

        # Compound expression
        await Post.objects.filter(pk=1).update(score=F("likes") * 2 - F("dislikes"))

        # Filter using another column's value
        await Post.objects.filter(views__gte=F("min_views"))
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def _combine(self, other: Any, op: str) -> _FExpr:
        return _FExpr(self, op, other)

    def __add__(self, other: Any) -> _FExpr:
        return self._combine(other, "+")

    def __radd__(self, other: Any) -> _FExpr:
        return _FExpr(other, "+", self)

    def __sub__(self, other: Any) -> _FExpr:
        return self._combine(other, "-")

    def __rsub__(self, other: Any) -> _FExpr:
        return _FExpr(other, "-", self)

    def __mul__(self, other: Any) -> _FExpr:
        return self._combine(other, "*")

    def __rmul__(self, other: Any) -> _FExpr:
        return _FExpr(other, "*", self)

    def __truediv__(self, other: Any) -> _FExpr:
        return self._combine(other, "/")

    def __repr__(self) -> str:
        return f"F({self.name!r})"

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, F) and self.name == other.name


class _FExpr:
    """Arithmetic combination of F references and literals.

    Not instantiated directly - produced by F arithmetic operators.
    """

    __slots__ = ("lhs", "op", "rhs")

    def __init__(self, lhs: Any, op: str, rhs: Any) -> None:
        self.lhs = lhs
        self.op = op
        self.rhs = rhs

    def _combine(self, other: Any, op: str) -> _FExpr:
        return _FExpr(self, op, other)

    def __add__(self, other: Any) -> _FExpr:
        return self._combine(other, "+")

    def __sub__(self, other: Any) -> _FExpr:
        return self._combine(other, "-")

    def __mul__(self, other: Any) -> _FExpr:
        return self._combine(other, "*")

    def __truediv__(self, other: Any) -> _FExpr:
        return self._combine(other, "/")

    def __repr__(self) -> str:
        return f"_FExpr({self.lhs!r} {self.op} {self.rhs!r})"

    def __hash__(self) -> int:
        lhs_hash = hash(self.lhs) if isinstance(self.lhs, (F, _FExpr)) else hash(str(self.lhs))
        rhs_hash = hash(self.rhs) if isinstance(self.rhs, (F, _FExpr)) else hash(str(self.rhs))
        return hash((lhs_hash, self.op, rhs_hash))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, _FExpr):
            return False
        return self.lhs == other.lhs and self.op == other.op and self.rhs == other.rhs


# -- Aggregate expressions ----------------------------------------------------


class _Aggregate:
    """Base class for SQL aggregate functions used in ``aggregate()`` / ``annotate()``."""

    __slots__ = ("field", "distinct")
    func: str = ""

    def __init__(self, field: str, distinct: bool = False) -> None:
        self.field = field
        self.distinct = distinct

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.field!r})"


class Count(_Aggregate):
    """``COUNT(field)`` aggregate."""

    func = "count"


class Sum(_Aggregate):
    """``SUM(field)`` aggregate."""

    func = "sum"


class Avg(_Aggregate):
    """``AVG(field)`` aggregate."""

    func = "avg"


class Max(_Aggregate):
    """``MAX(field)`` aggregate."""

    func = "max"


class Min(_Aggregate):
    """``MIN(field)`` aggregate."""

    func = "min"


# -- Q object -----------------------------------------------------------------


class Q:
    """Encapsulate filter conditions supporting ``|`` (OR), ``&`` (AND), ``~`` (NOT).

    Use with :meth:`~QuerySet.filter` / :meth:`~QuerySet.exclude` to express
    conditions that cannot be written with plain ``**kwargs``.

    Example::

        from openviper.db.models import Q

        # OR
        posts = await Post.objects.filter(Q(published=True) | Q(featured=True)).all()

        # NOT
        posts = await Post.objects.filter(~Q(status="draft")).all()

        # AND via & operator (same result as multiple kwargs)
        posts = await Post.objects.filter(
            Q(published=True) & Q(views__gte=100)
        ).all()

        # Compound: (title contains 'python' OR views >= 1000) AND published=True
        posts = await Post.objects.filter(
            Q(title__icontains="python") | Q(views__gte=1000),
            published=True,
        ).all()
    """

    __slots__ = ("connector", "negated", "children")
    AND = "AND"
    OR = "OR"

    def __init__(self, **kwargs: Any) -> None:
        self.connector: str = self.AND
        self.negated: bool = False
        self.children: list[Any] = list(kwargs.items())

    def _combine(self, other: Q, conn: str) -> Q:
        q = Q()
        q.connector = conn
        q.children = [self, other]
        return q

    def __and__(self, other: Q) -> Q:
        return self._combine(other, self.AND)

    def __or__(self, other: Q) -> Q:
        return self._combine(other, self.OR)

    def __invert__(self) -> Q:
        q = Q()
        q.connector = self.connector
        q.children = list(self.children)
        q.negated = not self.negated
        return q

    def __repr__(self) -> str:
        return (
            f"Q(connector={self.connector!r}, negated={self.negated}, children={self.children!r})"
        )


def check_primary_keys() -> None:
    """Validate that no registered model defines primary_key=True on a non-id field.

    The ORM auto-injects an 'id' AutoField as the primary key for every
    concrete model. Defining primary_key=True on a differently-named field
    results in two PRIMARY KEY columns at the database level.

    Call this from makemigrations and migrate before running any SQL.
    """
    errors: list[str] = []
    for model_cls in ModelMeta.registry.values():
        if getattr(model_cls, "_is_abstract", False):
            continue
        non_id_pks = [
            fname
            for fname, fobj in model_cls._fields.items()
            if getattr(fobj, "primary_key", False) and fname != "id"
        ]
        if non_id_pks:
            errors.append(
                f"  Model '{model_cls.__name__}' defines primary_key=True on "
                f"field(s) {non_id_pks!r}. The primary key field must be named "
                f"'id'. The ORM auto-creates an 'id' primary key - remove "
                f"primary_key=True from those fields or rename them to 'id'."
            )
    if errors:
        raise ValueError("Invalid primary key configuration:\n" + "\n".join(errors))


_MAX_CURSOR_SIZE: int = 10 * 1024  # 10 KB - prevents memory exhaustion from malicious cursors


def cursor_encode(values: dict[str, Any]) -> str:
    """Encode a dict of field→value pairs into an opaque cursor string."""
    raw = json.dumps(values, default=str, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def cursor_decode(cursor: str) -> dict[str, Any] | None:
    """Decode a cursor string produced by ``cursor_encode``.

    Rejects cursors whose decoded payload exceeds the size limit to
    prevent memory exhaustion from maliciously crafted inputs.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        if len(raw) > _MAX_CURSOR_SIZE:
            logger.debug("Cursor payload exceeds size limit (%d bytes)", len(raw))
            return None
        return cast("dict[str, Any]", json.loads(raw))
    except Exception:
        logger.debug("Cursor decode failed", exc_info=True)
        return None


def build_keyset_q(order_fields: list[str], cursor_values: dict[str, Any]) -> Q | None:
    """Build a Q filter that positions the query after the cursor row.

    For ``ORDER BY f1 ASC, f2 ASC`` with last-seen values ``{f1: v1, f2: v2}``
    the resulting filter is::

        (f1 > v1) | (f1 = v1 & f2 > v2)

    DESC fields use ``__lt`` instead of ``__gt``.
    Returns ``None`` when any required cursor value is missing.
    """
    or_parts: list[Q] = []
    for i, field_expr in enumerate(order_fields):
        is_desc = field_expr.startswith("-")
        fname = field_expr.lstrip("-")
        if fname not in cursor_values:
            break
        # The leading field uses a strict inequality to skip past the cursor row itself.
        lookup = f"{fname}__lt" if is_desc else f"{fname}__gt"
        part: Q = Q(**{lookup: cursor_values[fname]})
        # Tie-breaking on preceding fields preserves total ordering across duplicate values.
        for prev_expr in reversed(order_fields[:i]):
            prev_fname = prev_expr.lstrip("-")
            if prev_fname not in cursor_values:
                break
            part = Q(**{prev_fname: cursor_values[prev_fname]}) & part
        or_parts.append(part)
    if not or_parts:
        return None
    result = or_parts[0]
    for part in or_parts[1:]:
        result = result | part
    return result


# -- Manager (QuerySet factory) ------------------------------------------------


class Manager:
    """Default model manager - provides queryset-factory methods.

    Access via ``Model.objects``.
    """

    _queryset_class: type[QuerySet] | None = None

    @property
    def queryset_class(self) -> type[QuerySet]:
        """Return the queryset class, defaulting to QuerySet if not overridden."""
        return self._queryset_class or QuerySet

    def __init__(self, model_class: type[Model]) -> None:
        self.model = model_class

    def all(self) -> QuerySet:
        return self.queryset_class(self.model)

    def filter(self, *args: Any, **kwargs: Any) -> QuerySet:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        return self.queryset_class(self.model, ignore_permissions=ignore_permissions).filter(
            *args, **kwargs
        )

    def exclude(self, *args: Any, **kwargs: Any) -> QuerySet:
        return self.queryset_class(self.model).exclude(*args, **kwargs)

    def order_by(self, *fields: str) -> QuerySet:
        return self.queryset_class(self.model).order_by(*fields)

    def only(self, *fields: str) -> QuerySet:
        return self.queryset_class(self.model).only(*fields)

    def defer(self, *fields: str) -> QuerySet:
        return self.queryset_class(self.model).defer(*fields)

    def using(self, alias: str) -> QuerySet:
        """Return a QuerySet routed to the database *alias*.

        .. code-block:: python

           users = await User.objects.using('replica').all()
        """
        return self.queryset_class(self.model).using(alias)

    def distinct(self) -> QuerySet:
        return self.queryset_class(self.model).distinct()

    def annotate(self, **kwargs: Any) -> QuerySet:
        return self.queryset_class(self.model).annotate(**kwargs)

    def select_related(self, *fields: str) -> QuerySet:
        return self.queryset_class(self.model).select_related(*fields)

    def prefetch_related(self, *fields: str) -> QuerySet:
        return self.queryset_class(self.model).prefetch_related(*fields)

    async def values(self, *fields: str) -> list[dict[str, Any]]:
        return await self.queryset_class(self.model).values(*fields)

    async def values_list(
        self, *fields: str, flat: bool = False
    ) -> list[tuple[Any, ...]] | list[Any]:
        return await self.queryset_class(self.model).values_list(*fields, flat=flat)

    async def aggregate(self, **kwargs: Any) -> dict[str, Any]:
        return await self.queryset_class(self.model).aggregate(**kwargs)

    async def explain(self) -> str:
        return await self.queryset_class(self.model).explain()

    async def iterator(self, chunk_size: int = 2000) -> AsyncGenerator[Model]:
        async for inst in self.queryset_class(self.model).iterator(chunk_size=chunk_size):
            yield inst

    async def batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        async for batch in self.queryset_class(self.model).batch(size=size):
            yield batch

    async def id_batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        async for batch in self.queryset_class(self.model).id_batch(size=size):
            yield batch

    async def first(self) -> Model | None:
        return await self.queryset_class(self.model).first()

    async def last(self) -> Model | None:
        return await self.queryset_class(self.model).last()

    async def count(self) -> int:
        return await self.queryset_class(self.model).count()

    async def exists(self) -> bool:
        return await self.queryset_class(self.model).exists()

    async def get(self, **kwargs: Any) -> Model:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        qs = self.queryset_class(self.model, ignore_permissions=ignore_permissions)
        return await qs.filter(**kwargs).get()

    async def get_or_none(self, **kwargs: Any) -> Model | None:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        try:
            return await self.get(ignore_permissions=ignore_permissions, **kwargs)
        except DoesNotExist:
            return None

    async def create(self, **kwargs: Any) -> Model:
        if self.model._meta.single and await self.filter(ignore_permissions=True).exists():
            raise SingleModelAlreadyExistsError(
                f"{self.model.__name__} allows only one logical record."
            )
        instance = self.model(**kwargs)
        await instance.save()
        return instance

    async def get_single(self) -> Model:
        """Return the canonical record for a single model."""
        result = await self.filter(ignore_permissions=True).first()
        if result is None:
            raise SingleModelDoesNotExist(f"{self.model.__name__} has no single record.")
        return result

    async def get_or_create_single(self, **kwargs: Any) -> Model:
        """Return the single record, creating it when absent."""
        try:
            return await self.get_single()
        except SingleModelDoesNotExist:
            return await self.create_single(**kwargs)

    async def create_single(self, **kwargs: Any) -> Model:
        """Create the record for a single model if it does not exist."""
        if await self.filter(ignore_permissions=True).exists():
            raise SingleModelAlreadyExistsError(
                f"{self.model.__name__} allows only one logical record."
            )
        return await self.create(**kwargs)

    async def update_single(self, **kwargs: Any) -> Model:
        """Update and return the record for a single model."""
        instance = await self.get_single()
        for field_name, value in kwargs.items():
            setattr(instance, field_name, value)
        await instance.save(ignore_permissions=True)
        return instance

    async def get_or_create(
        self, defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[Model, bool]:
        try:
            obj = await self.get(**kwargs)
            return obj, False
        except DoesNotExist:
            params = {**kwargs, **(defaults or {})}
            try:
                obj = await self.create(**params)
                return obj, True
            except IntegrityError:
                # A concurrent coroutine may have inserted the row between
                # our DoesNotExist check and create(); fetch it instead.
                obj = await self.get(**kwargs)
                return obj, False

    async def bulk_create(
        self, objs: list[Model], ignore_permissions: bool = False, batch_size: int | None = None
    ) -> list[Model]:
        token = None
        if ignore_permissions:
            token = ignore_permissions_ctx.set(True)

        try:
            await check_permission_for_model(
                self.model, "create", ignore_permissions=ignore_permissions
            )
            for obj in objs:
                obj._apply_auto_fields()
            records = [o._to_dict() for o in objs]

            model_path = f"{self.model.__module__}.{self.model.__name__}"
            self._trigger_bulk_event(model_path, "pre_bulk_create", objs)

            stmt = self.model._get_insert_statement()
            # A single transaction with executemany is ~40-60% faster than per-row inserts.
            async with begin() as conn:
                if batch_size is not None and batch_size > 0 and len(records) > batch_size:
                    # Batching within one transaction avoids per-row commit overhead.
                    for i in range(0, len(records), batch_size):
                        batch = records[i : i + batch_size]
                        await conn.execute(stmt, batch)
                else:
                    await conn.execute(stmt, records)

            self._trigger_bulk_event(model_path, "post_bulk_create", objs)
            return objs
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def bulk_update(
        self,
        objs: list[Model],
        fields: list[str],
        ignore_permissions: bool = False,
        batch_size: int | None = None,
    ) -> int:
        """Bulk-update *fields* on a list of model instances.

        Issues one ``UPDATE`` per object (or batched if *batch_size* is set).
        Returns the total number of rows updated.

        .. code-block:: python

           posts = await Post.objects.filter(published=False).all()
           for post in posts:
               post.published = True
           updated = await Post.objects.bulk_update(posts, fields=["published"])
        """
        token = None
        if ignore_permissions:
            token = ignore_permissions_ctx.set(True)

        try:
            await check_permission_for_model(
                self.model, "update", ignore_permissions=ignore_permissions
            )
            model_path = f"{self.model.__module__}.{self.model.__name__}"
            self._trigger_bulk_event(model_path, "pre_bulk_update", objs)

            total = await execute_bulk_update(self.model, objs, fields, batch_size=batch_size)

            self._trigger_bulk_event(model_path, "post_bulk_update", objs)
            return total
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    @staticmethod
    def _trigger_bulk_event(model_path: str, event_name: str, objs: list[Any]) -> None:
        """Fire a bulk lifecycle event (best-effort, exceptions suppressed)."""
        try:
            dispatcher = get_dispatcher()
            if dispatcher is not None:
                dispatcher.trigger(model_path, event_name, objs)
            else:
                dispatch_decorator_handlers(model_path, event_name, objs)
        except Exception:
            logger.debug("Event dispatch failed for %s.%s", model_path, event_name, exc_info=True)

    async def update_or_create(
        self,
        defaults: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[Model, bool]:
        """Look up an object matching *kwargs*; update it with *defaults*, or create it.

        Returns a ``(instance, created)`` tuple where *created* is ``True``
        when the object did not previously exist.

        Args:
            defaults: Fields to update on the existing object, or merge into
                the new object on create.
            **kwargs: Lookup parameters used to find the existing object.

        .. code-block:: python

            post, created = await Post.objects.update_or_create(
                slug="hello-world",
                defaults={"title": "Hello World", "published": True},
            )
        """
        try:
            obj = await self.get(**kwargs)
            for field_name, value in (defaults or {}).items():
                setattr(obj, field_name, value)
            await obj.save()
            return obj, False
        except DoesNotExist:
            params = {**kwargs, **(defaults or {})}
            try:
                obj = await self.create(**params)
                return obj, True
            except IntegrityError:
                obj = await self.get(**kwargs)
                for field_name, value in (defaults or {}).items():
                    setattr(obj, field_name, value)
                await obj.save()
                return obj, False

    async def in_bulk(
        self,
        id_list: list[Any] | None = None,
        *,
        field_name: str = "id",
    ) -> dict[Any, Model]:
        """Return a dictionary mapping each ID in *id_list* to its model instance.

        If *id_list* is ``None`` or omitted, returns a mapping of **all** rows
        (subject to the configured ``MAX_QUERY_ROWS`` limit).

        Args:
            id_list: List of primary-key (or field) values to fetch.
            field_name: Which field to use as the dict key. Defaults to ``"id"``.

        Returns:
            ``{value: instance}`` mapping.

        .. code-block:: python

            posts = await Post.objects.in_bulk([1, 2, 3])
            # {1: <Post pk=1>, 2: <Post pk=2>, 3: <Post pk=3>}
        """
        qs: QuerySet = QuerySet(self.model)
        if id_list is not None:
            qs = qs.filter(**{f"{field_name}__in": id_list})
        instances = await qs.all()
        return {getattr(inst, field_name): inst for inst in instances}

    @classmethod
    def from_queryset(cls, queryset_class: type[QuerySet]) -> type[Manager]:
        """Return a new Manager subclass that uses *queryset_class* for all queries.

        This enables custom queryset methods to be called directly on the manager.

        .. code-block:: python

            class PublishedQuerySet(QuerySet):
                def published(self) -> QuerySet:
                    return self.filter(published=True)

            PublishedManager = Manager.from_queryset(PublishedQuerySet)

            class Post(Model):
                objects = PublishedManager()
                published_at = DateTimeField(null=True)
                published = BooleanField(default=False)
        """

        manager_name = f"{cls.__name__}From{queryset_class.__name__}"
        dynamic_manager = type(
            manager_name,
            (cls,),
            {"_queryset_class": queryset_class, "__module__": cls.__module__},
        )
        return cast("type[Manager]", dynamic_manager)

    def __repr__(self) -> str:
        return f"Manager(model={self.model.__name__})"


# TraversalStep and TraversalLookup live in _traversal.py to break the circular dependency
# between executor.py and models.py; re-exporting here preserves backward compatibility.


class Page:
    """Query results page with metadata.

    Attributes:
        items: List of model instances for the current page.
        number: Current page number (1-indexed).
        page_size: Maximum number of items per page.
        total_count: Total number of records matching the query.
        num_pages: Total number of pages available.
        next_cursor: Opaque keyset cursor string for the next page, or ``None``
            when all results have been returned.  Present only when the query
            was executed with a cursor; ``None`` for OFFSET-based pages.
    """

    __slots__ = ("items", "number", "page_size", "total_count", "num_pages", "next_cursor")

    def __init__(
        self,
        items: list[Model],
        number: int,
        page_size: int,
        total_count: int,
        next_cursor: str | None = None,
    ) -> None:
        self.items = items
        self.number = number
        self.page_size = page_size
        self.total_count = total_count
        self.num_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
        self.next_cursor = next_cursor

    @property
    def has_next(self) -> bool:
        if self.next_cursor is not None:
            return True
        return self.number < self.num_pages

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def next_page_number(self) -> int:
        return self.number + 1

    @property
    def previous_page_number(self) -> int:
        return self.number - 1

    def __repr__(self) -> str:
        return f"<Page {self.number} of {self.num_pages} ({len(self.items)} items)>"


# -- Traversal key remapping ---------------------------------------------------


def remap_traversal_keys(
    rows: list[dict[str, Any]], fields: tuple[str, ...] | None
) -> list[dict[str, Any]]:
    """Remap traversal keys to their final field segment.

    ``"user__username"`` becomes ``"username"`` in the output dict.
    When two traversal fields share the same final key (collision),
    the full traversal key is preserved to avoid silent data loss.
    """
    if not fields:
        return rows
    traversal_fields = [f for f in fields if "__" in f]
    if not traversal_fields:
        return rows
    final_keys: dict[str, str] = {}
    seen_shorts: set[str] = set()
    collisions: set[str] = set()
    for tf in traversal_fields:
        short = tf.rsplit("__", 1)[-1]
        if short in seen_shorts:
            collisions.add(short)
        seen_shorts.add(short)
        final_keys[tf] = short
    remap: dict[str, str] = {
        tf: short for tf, short in final_keys.items() if short not in collisions
    }
    if not remap:
        return rows
    return [{remap.get(k, k): v for k, v in row.items()} for row in rows]


def remap_field_keys(fields: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Return field names with traversal keys remapped to their final segment.

    Used by ``values_list`` to look up values in remapped result dicts.
    """
    if not fields:
        return fields
    traversal_fields = [f for f in fields if "__" in f]
    if not traversal_fields:
        return fields
    seen_shorts: set[str] = set()
    collisions: set[str] = set()
    for tf in traversal_fields:
        short = tf.rsplit("__", 1)[-1]
        if short in seen_shorts:
            collisions.add(short)
        seen_shorts.add(short)
    remap: dict[str, str] = {
        tf: tf.rsplit("__", 1)[-1]
        for tf in traversal_fields
        if tf.rsplit("__", 1)[-1] not in collisions
    }
    if not remap:
        return fields
    return tuple(remap.get(f, f) for f in fields)


# -- QuerySet ------------------------------------------------------------------


class QuerySet:
    """Lazy chainable query builder.

    Filters, ordering and slicing are accumulated until awaited.

    Example:
        >>> qs = User.objects.filter(is_active=True).order_by("-created_at")
        >>> users = await qs.all()
        >>> count = await qs.count()
    """

    def __init__(self, model: type[Model], ignore_permissions: bool = False) -> None:
        self._model = model
        self._filters: list[dict[str, Any]] = []
        self._excludes: list[dict[str, Any]] = []
        self._q_filters: list[Q] = []
        self._order: list[str] = list(getattr(model, "_ordering", []))
        self._limit: int | None = None
        self._offset: int | None = None
        self._distinct: bool = False
        self._select_related: list[str] = []
        self._prefetch_related: list[str] = []
        self._ignore_permissions = ignore_permissions
        self._only_fields: list[str] = []
        self._defer_fields: list[str] = []
        self._annotations: dict[str, Any] = {}
        self._for_update: bool = False
        self._for_update_nowait: bool = False
        self._for_update_skip_locked: bool = False
        self._db_alias: str | None = None

    def filter(self, *args: Any, **kwargs: Any) -> QuerySet:
        ignore_permissions = kwargs.pop("ignore_permissions", None)
        clone = self._clone()
        if ignore_permissions is not None:
            clone._ignore_permissions = ignore_permissions
        if kwargs:
            clone._filters.append(kwargs)
        for q in args:
            clone._q_filters.append(q)
        return clone

    def exclude(self, *args: Any, **kwargs: Any) -> QuerySet:
        clone = self._clone()
        if kwargs:
            clone._excludes.append(kwargs)
        for q in args:
            clone._q_filters.append(~q)
        return clone

    def order_by(self, *fields: str) -> QuerySet:
        clone = self._clone()
        clone._order = list(fields)
        return clone

    def limit(self, n: int) -> QuerySet:
        clone = self._clone()
        clone._limit = n
        return clone

    def offset(self, n: int) -> QuerySet:
        clone = self._clone()
        clone._offset = n
        return clone

    def distinct(self) -> QuerySet:
        clone = self._clone()
        clone._distinct = True
        return clone

    def select_for_update(
        self,
        nowait: bool = False,
        skip_locked: bool = False,
    ) -> QuerySet:
        """Apply ``SELECT FOR UPDATE`` locking to the query.

        Rows matched by the query will be locked until the current
        transaction commits or rolls back.

        Args:
            nowait: If ``True``, raise an error immediately rather than
                waiting when a conflicting lock is held.
            skip_locked: If ``True``, skip rows that are currently locked
                rather than waiting.  ``nowait`` and ``skip_locked``
                are mutually exclusive.

        .. code-block:: python

            async with atomic():
                post = await Post.objects.select_for_update().filter(id=1).get()
                post.views += 1
                await post.save()
        """
        if nowait and skip_locked:
            raise ValueError("select_for_update() cannot use both nowait=True and skip_locked=True")
        clone = self._clone()
        clone._for_update = True
        clone._for_update_nowait = nowait
        clone._for_update_skip_locked = skip_locked
        return clone

    def select_related(self, *fields: str) -> QuerySet:
        clone = self._clone()
        clone._select_related = list(fields)
        return clone

    def prefetch_related(self, *fields: str) -> QuerySet:
        clone = self._clone()
        clone._prefetch_related = list(fields)
        return clone

    def only(self, *fields: str) -> QuerySet:
        """Restrict the SELECT to only the given field names.

        All other fields will be ``None`` on the returned instances.  The
        primary key is always included automatically.

        .. code-block:: python

           posts = await Post.objects.only("id", "title").all()
        """
        clone = self._clone()
        clone._only_fields = list(fields)
        clone._defer_fields = []
        return clone

    def defer(self, *fields: str) -> QuerySet:
        """Exclude the given field names from the SELECT.

        All other fields are still fetched.  Cannot be combined with
        ``only()`` - the last call wins.

        .. code-block:: python

           posts = await Post.objects.defer("body", "raw_html").all()
        """
        clone = self._clone()
        clone._defer_fields = list(fields)
        clone._only_fields = []
        return clone

    def using(self, alias: str) -> QuerySet:
        """Route this query to the database *alias*.

        Overrides the router for this query chain.  Unknown aliases
        raise ``DatabaseAliasNotFoundError`` when the query executes.

        .. code-block:: python

           users = await User.objects.using('replica').all()
           await User.objects.using('default').create(email='a@example.com')
        """
        clone = self._clone()
        clone._db_alias = alias
        return clone

    def annotate(self, **kwargs: Any) -> QuerySet:
        """Add computed columns to each result row.

        Values may be :class:`F` expressions, :class:`_Aggregate` instances,
        or plain SQLAlchemy column expressions.

        .. code-block:: python

           from openviper.db.models import Count, F

           posts = await (
               Post.objects
               .annotate(like_count=Count("likes"), double_views=F("views") * 2)
               .all()
           )
           for post in posts:
               print(post.like_count, post.double_views)
        """
        clone = self._clone()
        clone._annotations = {**self._annotations, **kwargs}
        return clone

    def virtual_backend(self) -> VirtualBackend:
        """Return the configured backend for a virtual model."""
        return backend_registry.get(self._model._meta.backend)

    def virtual_query_spec(self) -> QuerySpec:
        """Translate supported QuerySet state into a virtual backend query."""
        if self._q_filters or self._excludes:
            raise UnsupportedVirtualQueryError(
                "Virtual model queries do not support Q filters or exclude()."
            )

        backend = self.virtual_backend()
        filters: dict[str, object] = {}
        filter_clauses: list[FilterClause] = []
        filter_ops = {
            "exact": FilterOp.EQ,
            "ne": FilterOp.NE,
            "gt": FilterOp.GT,
            "gte": FilterOp.GTE,
            "lt": FilterOp.LT,
            "lte": FilterOp.LTE,
            "in": FilterOp.IN,
            "not_in": FilterOp.NOT_IN,
            "contains": FilterOp.CONTAINS,
            "icontains": FilterOp.ICONTAINS,
            "startswith": FilterOp.STARTSWITH,
            "endswith": FilterOp.ENDSWITH,
            "isnull": FilterOp.IS_NULL,
        }
        for filter_dict in self._filters:
            for key, value in filter_dict.items():
                field_name, separator, lookup = key.partition("__")
                if not separator:
                    filters[field_name] = value
                    continue
                operator = filter_ops.get(lookup)
                if operator is None:
                    raise UnsupportedVirtualQueryError(
                        f"Virtual model lookup '{lookup}' is not supported."
                    )
                filter_clauses.append(FilterClause(field_name, operator, value))

        capabilities = backend.capabilities
        if (filters or filter_clauses) and not capabilities.supports_filter:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support filter."
            )
        if filter_clauses and not capabilities.supports_filter_ops:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support filter lookups."
            )
        if self._order and not capabilities.supports_order_by:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support order_by."
            )
        if self._limit is not None and not capabilities.supports_limit:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support limit."
            )
        if self._offset is not None and not capabilities.supports_offset:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support offset."
            )
        if self._distinct and not capabilities.supports_distinct:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(backend).__name__}' does not support distinct."
            )

        return QuerySpec(
            filters=filters,
            filter_clauses=tuple(filter_clauses),
            limit=self._limit,
            offset=self._offset,
            order_by=tuple(self._order) or None,
            distinct=self._distinct,
            only_fields=tuple(self._only_fields),
            defer_fields=tuple(self._defer_fields),
        )

    async def virtual_list(self) -> list[Model]:
        """Fetch and hydrate rows through the configured virtual backend."""
        if self._model._meta.single:
            return await self._virtual_list_single()
        rows = await self.virtual_backend().list(self._model, self.virtual_query_spec())
        return [self._model._from_row_fast(dict(row)) for row in rows]

    async def _virtual_list_single(self) -> list[Model]:
        """Fetch the single logical record, then apply user filters in-memory.

        Virtual backends may contain stray rows due to race conditions or
        manual DB edits.  For single models the framework must only expose
        the first logical record regardless of how many rows exist.
        """
        backend = self.virtual_backend()
        # Fetch the single record without user filters so we always get
        # the same "first" row regardless of what the caller filtered on.
        single_spec = QuerySpec(
            filters={},
            filter_clauses=(),
            limit=1,
            offset=None,
            order_by=None,
            distinct=False,
            only_fields=tuple(self._only_fields),
            defer_fields=tuple(self._defer_fields),
        )
        rows = await backend.list(self._model, single_spec)
        if not rows:
            return []
        instance = self._model._from_row_fast(dict(rows[0]))
        # Apply user filters in-memory so filter(id=2).exists() correctly
        # returns False when the single record has id=1.
        if self._filters or self._excludes:
            for filt in self._filters:
                for key, value in filt.items():
                    if getattr(instance, key, None) != value:
                        return []
            for excl in self._excludes:
                for key, value in excl.items():
                    if getattr(instance, key, None) == value:
                        return []
        return [instance]

    def virtual_primary_key_filter(self) -> object | None:
        """Return an id equality filter suitable for backend.get()."""
        if len(self._filters) != 1 or self._q_filters or self._excludes:
            return None
        filter_dict = self._filters[0]
        if len(filter_dict) != 1:
            return None
        if "id" in filter_dict:
            return cast("object", filter_dict["id"])
        if "pk" in filter_dict:
            return cast("object", filter_dict["pk"])
        return None

    async def paginate(
        self,
        page_number: int = 1,
        page_size: int = 20,
        *,
        cursor: str | None = None,
    ) -> Page:
        """Paginate the query and return a :class:`Page`.

        When *cursor* is supplied the query uses keyset pagination - the
        database seeks directly to the cursor position so performance is
        O(log N) regardless of how deep into the result set you are.

        When *cursor* is omitted the query falls back to OFFSET-based
        pagination (backward-compatible).

        Args:
            page_number: 1-indexed page number (OFFSET mode only).
            page_size: Number of items per page.
            cursor: Opaque cursor returned by a previous :class:`Page`.

        Returns:
            :class:`Page` instance.
        """
        if page_number < 1:
            raise ValueError("Page number must be >= 1.")

        if cursor is not None:
            # Running COUNT and fetch in parallel halves the latency of keyset pagination.
            cursor_values = cursor_decode(cursor)
            order_fields: list[str] = list(self._order)
            keyset_q = (
                build_keyset_q(order_fields, cursor_values)
                if cursor_values and order_fields
                else None
            )
            page_qs = self.filter(keyset_q) if keyset_q is not None else self

            total_count, items = await asyncio.gather(
                self.count(),
                page_qs.limit(page_size).all(),
            )

            next_cursor: str | None = None
            if len(items) == page_size and order_fields:
                last = items[-1]
                next_cursor = cursor_encode(
                    {f.lstrip("-"): getattr(last, f.lstrip("-"), None) for f in order_fields}
                )
            return Page(items, page_number, page_size, total_count, next_cursor=next_cursor)

        # Running COUNT and fetch in parallel halves the latency of offset-based pagination.
        offset = (page_number - 1) * page_size

        total_count, items = await asyncio.gather(
            self.count(),
            self.limit(page_size).offset(offset).all(),
        )

        # Encode the last row's ordering values as an opaque cursor for
        # fast subsequent page fetches.
        next_cursor_offset: str | None = None
        if len(items) == page_size and self._order:
            last = items[-1]
            next_cursor_offset = cursor_encode(
                {f.lstrip("-"): getattr(last, f.lstrip("-"), None) for f in self._order}
            )

        return Page(items, page_number, page_size, total_count, next_cursor=next_cursor_offset)

    async def all(self) -> list[Model]:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_perm_cached(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                return await self.virtual_list()
            rows = await execute_select(self)
            # Prefixed keys belong to related models and must not leak into
            # the main model's __init__.
            sr_prefixes = tuple(f"{fn}__" for fn in self._select_related)
            instances: list[Model] = []

            if self._select_related:
                # Pre-compute column mappings once rather than per-row to reduce string operations.
                sr_mappings: dict[str, tuple[type, list[tuple[str, str]]]] = {}
                for field_name in self._select_related:
                    field = self._model._fields.get(field_name)
                    if field is None or not hasattr(field, "resolve_target"):
                        continue
                    related_cls = cast("Any", field).resolve_target()
                    if related_cls is None:
                        continue
                    prefix = f"{field_name}__"
                    # Pre-compute prefix-to-field mappings once to avoid
                    # repeated string ops per row.
                    key_pairs = [
                        (col, col[len(prefix) :])
                        for col in (rows[0] if rows else {})
                        if col.startswith(prefix)
                    ]
                    sr_mappings[field_name] = (related_cls, key_pairs)

            for row in rows:
                main_row = (
                    {k: v for k, v in row.items() if not k.startswith(sr_prefixes)}
                    if sr_prefixes
                    else row
                )
                instance = self._model._from_row_fast(main_row)
                if self._select_related:
                    self._hydrate_select_related_fast(instance, row, sr_mappings)
                instances.append(instance)
            if self._prefetch_related:
                await self._do_prefetch_related(instances)
            return instances
        except ModelPermissionError:
            return []
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def get(self) -> Model:
        if self._model._meta.virtual:
            primary_key = self.virtual_primary_key_filter()
            if primary_key is not None:
                row = await self.virtual_backend().get(self._model, primary_key)
                if row is None:
                    raise DoesNotExist(f"{self._model.__name__} matching query does not exist.")
                return self._model._from_row_fast(dict(row))
        clone = self.limit(2)
        results = await clone.all()
        if not results:
            raise DoesNotExist(f"{self._model.__name__} matching query does not exist.")
        if len(results) > 1:
            raise MultipleObjectsReturned(f"get() returned more than one {self._model.__name__}.")
        return results[0]

    async def first(self) -> Model | None:
        results = await self.limit(1).all()
        return results[0] if results else None

    async def last(self) -> Model | None:
        if self._order:
            reversed_order = [f[1:] if f.startswith("-") else "-" + f for f in self._order]
            results = await self.order_by(*reversed_order).limit(1).all()
        else:
            results = await self.order_by("-id").limit(1).all()
        return results[0] if results else None

    async def count(self) -> int:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                if self._model._meta.single:
                    # Single models must filter in-memory to avoid stray rows.
                    return len(await self.virtual_list())
                backend = self.virtual_backend()
                query = self.virtual_query_spec()
                if backend.capabilities.supports_count:
                    return await backend.count(self._model, query)
                return len(await backend.list(self._model, query))
            return await execute_count(self)
        except ModelPermissionError:
            return 0
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def exists(self) -> bool:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_perm_cached(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                if self._model._meta.single:
                    # Single models must filter in-memory to avoid stray rows.
                    return bool(await self.virtual_list())
                backend = self.virtual_backend()
                query = self.virtual_query_spec()
                if backend.capabilities.supports_count:
                    return await backend.count(self._model, query) > 0
                exists_query = QuerySpec(
                    filters=query.filters,
                    filter_clauses=query.filter_clauses,
                    limit=1,
                    offset=query.offset,
                    order_by=query.order_by,
                    distinct=query.distinct,
                    only_fields=query.only_fields,
                    defer_fields=query.defer_fields,
                )
                return bool(await backend.list(self._model, exists_query))
            return await execute_exists(self)
        except ModelPermissionError:
            return False
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def delete(self) -> int:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "delete", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.single:
                raise SingleModelDeleteForbiddenError(
                    f"{self._model.__name__} single records cannot be deleted."
                )
            if self._model._meta.virtual:
                if self._model._meta.read_only:
                    raise ReadOnlyVirtualModelError(
                        f"{self._model.__name__} is configured as read-only."
                    )
                backend = self.virtual_backend()
                rows = await backend.list(self._model, self.virtual_query_spec())
                for row in rows:
                    await backend.delete(self._model, row["id"])
                return len(rows)
            return await execute_delete(self)
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def update(self, **kwargs: Any) -> int:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "update", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                if self._model._meta.read_only:
                    raise ReadOnlyVirtualModelError(
                        f"{self._model.__name__} is configured as read-only."
                    )
                backend = self.virtual_backend()
                rows = await backend.list(self._model, self.virtual_query_spec())
                for row in rows:
                    await backend.update(self._model, row["id"], kwargs)
                return len(rows)
            return await execute_update(self, kwargs)
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def values(self, *fields: str) -> list[dict[str, Any]]:
        """Execute the query and return each row as a plain ``dict``.

        If *fields* are given only those columns are included; otherwise all
        model columns plus any annotations are returned.

        .. code-block:: python

           rows = await Post.objects.filter(published=True).values("id", "title")
           # [{"id": 1, "title": "Hello"}, ...]
        """
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                if self._annotations:
                    raise UnsupportedVirtualQueryError(
                        "Virtual model values() does not support annotations."
                    )
                rows = await self.virtual_backend().list(
                    self._model,
                    self.virtual_query_spec(),
                )
                if not fields:
                    return [dict(row) for row in rows]
                wanted = set(fields)
                return [{key: value for key, value in row.items() if key in wanted} for row in rows]
            rows = await execute_values(self, fields or None)
            return remap_traversal_keys(rows, fields if fields else None)
        except ModelPermissionError:
            return []
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def values_list(
        self, *fields: str, flat: bool = False
    ) -> list[tuple[Any, ...]] | list[Any]:
        """Execute the query and return rows as tuples (or scalars if *flat*).

        *flat* may only be ``True`` when exactly one field is requested.

        .. code-block:: python

           ids = await Post.objects.values_list("id", flat=True)
           # [1, 2, 3, ...]

           pairs = await Post.objects.values_list("id", "title")
           # [(1, "Hello"), (2, "World"), ...]
        """
        if flat and len(fields) != 1:
            raise ValueError("values_list(flat=True) requires exactly one field.")
        rows = await self.values(*fields)
        if not rows:
            return []
        remapped = remap_field_keys(fields)
        if flat:
            key = remapped[0] if remapped else fields[0]
            return [row[key] for row in rows]
        keys = remapped if remapped else rows[0].keys()
        return [tuple(row[k] for k in keys) for row in rows]

    async def aggregate(self, **kwargs: Any) -> dict[str, Any]:
        """Execute aggregate functions and return a single result dict.

        Values must be :class:`_Aggregate` instances (``Count``, ``Sum``,
        ``Avg``, ``Max``, ``Min``).

        .. code-block:: python

           from openviper.db.models import Count, Sum, Avg

           result = await Post.objects.filter(published=True).aggregate(
               total=Count("id"),
               total_views=Sum("views"),
               avg_views=Avg("views"),
           )
           # {"total": 42, "total_views": 9820, "avg_views": 233.8}
        """
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            if self._model._meta.virtual:
                raise UnsupportedVirtualQueryError(
                    "Virtual model aggregate() requires backend-specific aggregation."
                )
            return await execute_aggregate(self, kwargs)
        except ModelPermissionError:
            return {}
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    async def explain(self) -> str:
        """Return the database EXPLAIN output for the current query.

        Useful for inspecting query plans and diagnosing performance issues.

        .. code-block:: python

           plan = await Post.objects.filter(published=True).explain()
           print(plan)
        """
        if self._model._meta.virtual:
            raise UnsupportedVirtualQueryError(
                "Virtual model queries do not expose SQL EXPLAIN plans."
            )
        return await execute_explain(self)

    def raw_sql(self) -> str:
        """Return the parameterized SQL query string for the current queryset.

        Compiles the query with parameter placeholders (not literal values)
        so that sensitive filter values are not exposed in the output.

        .. code-block:: python

           qs = Post.objects.filter(published=True).order_by("-created_at")
           print(qs.raw_sql())
        """
        if self._model._meta.virtual:
            raise UnsupportedVirtualQueryError("Virtual model queries do not compile to SQL.")
        table = get_table(self._model)
        stmt = sa.select(table)

        for filter_dict in self._filters:
            for key, value in filter_dict.items():
                if "__" in key:
                    field, _ = key.rsplit("__", 1)
                else:
                    field = key
                if field in table.c:
                    stmt = stmt.where(table.c[field] == value)

        for field_name in self._order:
            desc = field_name.startswith("-")
            col_name = field_name.lstrip("-")
            if col_name in table.c:
                col = table.c[col_name]
                stmt = stmt.order_by(col.desc() if desc else col.asc())

        if self._limit is not None:
            stmt = stmt.limit(self._limit)
        if self._offset is not None:
            stmt = stmt.offset(self._offset)

        if self._distinct:
            stmt = stmt.distinct()

        # Parameterised compilation prevents sensitive filter values from appearing in raw SQL.
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        return str(compiled)

    async def iterator(self, chunk_size: int = 2000) -> AsyncGenerator[Model]:
        """Yield model instances one at a time using PK-based pagination.

        Uses keyset (id > last_id) pagination instead of OFFSET for stable
        performance even on very large tables.

        .. code-block:: python

           async for post in Post.objects.filter(published=True).iterator(chunk_size=500):
               await process(post)
        """
        last_id = 0
        while True:
            chunk = await self.filter(id__gt=last_id).order_by("id").limit(chunk_size).all()
            if not chunk:
                break
            for instance in chunk:
                yield instance
            last_id = chunk[-1].pk
            if len(chunk) < chunk_size:
                break

    async def batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        """Yield successive lists of at most *size* model instances.

        Preferable to ``iterator()`` when downstream code needs to process
        groups (e.g. bulk inserts, batch notifications).

        .. code-block:: python

           async for batch in Post.objects.filter(published=True).batch(size=200):
               await index_search(batch)
        """
        offset = 0
        while True:
            chunk = await self.limit(size).offset(offset).all()
            if not chunk:
                break
            yield chunk
            if len(chunk) < size:
                break
            offset += size

    async def id_batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        """Yield successive lists of model instances using PK-based pagination.

        More stable than OFFSET-based pagination when the table is being
        written concurrently - rows inserted during iteration cannot shift
        pages.

        Requires an auto-incrementing integer ``id`` field (default on every
        OpenViper model).

        .. code-block:: python

           async for batch in Post.objects.filter(published=True).id_batch(size=500):
               await process_batch(batch)
        """
        last_id = 0
        while True:
            chunk = await self.filter(id__gt=last_id).order_by("id").limit(size).all()
            if not chunk:
                break
            yield chunk
            last_id = chunk[-1].pk
            if len(chunk) < size:
                break

    def _hydrate_select_related(self, instance: Model, row: dict[str, Any]) -> None:
        """Attach select_related model instances from prefixed row keys to *instance*.

        Also caches the related instances for smart descriptor access.
        """
        for field_name in self._select_related:
            field = self._model._fields.get(field_name)
            if field is None or not hasattr(field, "resolve_target"):
                continue
            related_cls = cast("Any", field).resolve_target()
            if related_cls is None:
                continue
            prefix = f"{field_name}__"
            related_row = {k[len(prefix) :]: v for k, v in row.items() if k.startswith(prefix)}
            if related_row and any(v is not None for v in related_row.values()):
                related_instance = related_cls._from_row_fast(related_row)
                instance._set_related(field_name, related_instance)
            else:
                instance._set_related(field_name, None)

    @staticmethod
    def _hydrate_select_related_fast(
        instance: Model,
        row: dict[str, Any],
        sr_mappings: dict[str, tuple[type, list[tuple[str, str]]]],
    ) -> None:
        """Fast path: use pre-computed column mappings to hydrate related objects."""
        for field_name, (related_cls, key_pairs) in sr_mappings.items():
            related_row = {unprefixed: row[prefixed] for prefixed, unprefixed in key_pairs}
            if related_row and any(v is not None for v in related_row.values()):
                related_instance = related_cls._from_row_fast(related_row)
                instance._set_related(field_name, related_instance)
            else:
                instance._set_related(field_name, None)

    async def _do_prefetch_related(self, instances: list[Model]) -> None:
        """Batch-load prefetch_related FK and M2M fields and attach them to *instances*.

        Collects all FK values from the main instances, groups by target model
        to deduplicate queries (e.g. multiple FKs to User become one query),
        issues queries in parallel via asyncio.gather, and sets the related
        objects as attributes on each instance.

        ManyToManyField entries are handled separately: each M2M field issues
        one query against the through table and stores a list of related objects
        on each instance's relation cache so that ``instance.field.all()``
        returns the cached list without a further database round-trip.
        """
        for field_name in self._prefetch_related:
            field = self._model._fields.get(field_name)
            if not isinstance(field, ManyToManyField):
                continue

            descriptor = getattr(self._model, field_name, None)
            if not isinstance(descriptor, ManyToManyDescriptor):
                continue

            source_pks = [inst.pk for inst in instances if inst.pk is not None]
            if not source_pks:
                for inst in instances:
                    inst._set_related(field_name, [])
                continue

            try:
                sample_mgr = descriptor.__get__(instances[0], type(instances[0]))
            except Exception:
                logger.debug("Prefetch descriptor access failed for %s", field_name, exc_info=True)
                continue

            if not isinstance(sample_mgr, ManyToManyManager):
                continue

            through_model = cast("Any", sample_mgr.through_model)
            target_model = cast("Any", sample_mgr.target_model)
            src_field = sample_mgr.source_field_name
            tgt_field = sample_mgr.target_field_name

            through_objs = await through_model.objects.filter(
                **{f"{src_field}__in": source_pks}
            ).all()

            src_to_tgt_pks: dict[Any, list[Any]] = {pk: [] for pk in source_pks}
            all_tgt_pks: list[Any] = []
            for tobj in through_objs:
                src_val = tobj.__dict__.get(f"{src_field}_id") or tobj.__dict__.get(src_field)
                tgt_val = tobj.__dict__.get(f"{tgt_field}_id") or tobj.__dict__.get(tgt_field)
                if isinstance(src_val, LazyFK):
                    src_val = src_val.fk_id
                if isinstance(tgt_val, LazyFK):
                    tgt_val = tgt_val.fk_id
                if src_val in src_to_tgt_pks and tgt_val is not None:
                    src_to_tgt_pks[src_val].append(tgt_val)
                    all_tgt_pks.append(tgt_val)

            target_map: dict[Any, Any] = {}
            if all_tgt_pks:
                for tgt_obj in await target_model.objects.filter(id__in=all_tgt_pks).all():
                    target_map[tgt_obj.pk] = tgt_obj

            for inst in instances:
                tgt_pks = src_to_tgt_pks.get(inst.pk, [])
                inst._set_related(
                    field_name,
                    [target_map[pk] for pk in tgt_pks if pk in target_map],
                )

        # (field_name, field, related_cls, fk_col)
        field_meta: list[tuple[str, Any, type, str]] = []
        # Grouping by target model deduplicates queries when multiple FKs point to the same model.
        grouped_ids: dict[type, set[int]] = {}

        for field_name in self._prefetch_related:
            field = self._model._fields.get(field_name)
            if field is None or not hasattr(field, "resolve_target"):
                continue
            related_cls = cast("Any", field).resolve_target()
            if related_cls is None:
                continue
            fk_col = field.column_name if isinstance(field, ForeignKey) else field_name
            is_fk = isinstance(field, ForeignKey)

            def _extract_id(
                inst: Any, _fk_col: str = fk_col, _is_fk: bool = is_fk, _fname: str = field_name
            ) -> int | None:
                val = inst.__dict__.get(_fk_col) if _is_fk else getattr(inst, _fname, None)
                if isinstance(val, int):
                    return val
                if isinstance(val, LazyFK) and isinstance(val.fk_id, int):
                    return val.fk_id
                return None

            fk_ids = {pk for pk in (_extract_id(inst) for inst in instances) if pk is not None}
            if not fk_ids:
                continue

            field_meta.append((field_name, field, related_cls, fk_col))
            grouped_ids.setdefault(related_cls, set()).update(fk_ids)

        if not grouped_ids:
            return

        cls_list = list(grouped_ids.keys())
        prefetch_tasks = [
            cls.objects.filter(id__in=list(ids)).all()
            for cls, ids in zip(cls_list, (grouped_ids[c] for c in cls_list), strict=False)
        ]
        prefetch_results = await asyncio.gather(*prefetch_tasks)

        # A single lookup dict per target model avoids repeated DB queries per instance.
        related_maps: dict[type, dict[Any, Any]] = {}
        for cls, result_list in zip(cls_list, prefetch_results, strict=False):
            related_maps[cls] = {ri.pk: ri for ri in result_list}

        for field_name, field, related_cls, fk_col in field_meta:
            related_map = related_maps.get(related_cls, {})
            for inst in instances:
                fk_val = (
                    inst.__dict__.get(fk_col)
                    if isinstance(field, ForeignKey)
                    else getattr(inst, field_name, None)
                )
                if isinstance(fk_val, int):
                    inst._set_related(field_name, related_map.get(fk_val))
                elif isinstance(fk_val, LazyFK) and isinstance(fk_val.fk_id, int):
                    inst._set_related(field_name, related_map.get(fk_val.fk_id))

    def __aiter__(self) -> QuerySet:
        self._iter_results: list[Any] | None = None
        self._iter_index = 0
        return self

    async def __anext__(self) -> Model:
        if self._iter_results is None:
            self._iter_results = await self.all()
        if self._iter_index >= len(self._iter_results):
            raise StopAsyncIteration
        result = self._iter_results[self._iter_index]
        self._iter_index += 1
        return result

    def __await__(self) -> Any:
        """Make QuerySet directly awaitable.

        ``await qs`` is equivalent to ``await qs.all()``, returning a list
        of model instances.

        Example::

            posts = await Post.objects.select_related("author").filter(author_id=1)
            post  = await Post.objects.select_related("author").filter(id=1).first()
        """
        return self.all().__await__()

    def _clone(self) -> QuerySet:
        clone = self.__class__(self._model)
        clone._filters = list(self._filters)
        clone._excludes = list(self._excludes)
        clone._q_filters = list(self._q_filters)
        clone._order = list(self._order)
        clone._limit = self._limit
        clone._offset = self._offset
        clone._distinct = self._distinct
        clone._select_related = list(self._select_related)
        clone._prefetch_related = list(self._prefetch_related)
        clone._ignore_permissions = self._ignore_permissions
        clone._only_fields = list(self._only_fields)
        clone._defer_fields = list(self._defer_fields)
        clone._annotations = dict(self._annotations)
        clone._for_update = self._for_update
        clone._for_update_nowait = self._for_update_nowait
        clone._for_update_skip_locked = self._for_update_skip_locked
        clone._db_alias = self._db_alias
        return clone

    def __repr__(self) -> str:
        return f"QuerySet(model={self._model.__name__}, filters={self._filters})"


# -- Model ---------------------------------------------------------------------

# -- Hook caller ---------------------------------------------------------------


async def call_hook(hook: Any, *args: Any) -> Any:
    """Call a lifecycle hook, tolerating both sync and async implementations.

    If a subclass overrides a hook as a plain ``def`` instead of ``async def``,
    we still call it safely without raising ``TypeError``.
    """
    result = hook(*args)
    if inspect.isawaitable(result):
        return await result
    return result


# -- Model ---------------------------------------------------------------------


class Model(metaclass=ModelMeta):
    """Base model class. Inherit to define database-backed models.

    Lifecycle Hooks
    ---------------
    Override any of these ``async`` methods in your model to hook into
    the persistence lifecycle.  All default implementations are no-ops.

    **Create flow** (``pk`` is ``None``)::

        before_validate → validate → before_insert → before_save
        → INSERT → after_insert → on_change

    **Update flow** (``pk`` is set)::

        before_validate → validate → before_save
        → UPDATE → on_update → on_change  (only if data changed)

    **Delete flow**::

        on_delete → DELETE → after_delete

    Example:
        .. code-block:: python

            class Article(Model):
                title = CharField(max_length=200)
                body  = TextField()
                author_id = IntegerField()
                published_at = DateTimeField(null=True)

                async def before_save(self) -> None:
                    self.title = self.title.strip()

                async def validate(self) -> None:
                    if not self.title:
                        raise ValueError("Title is required")

                async def after_insert(self) -> None:
                    print(f"Article {self.pk} created!")

                async def on_change(self, previous_state: dict[str, Any]) -> None:
                    print(f"Changed fields: {previous_state}")
    """

    _fields: ClassVar[dict[str, Field]]
    _table_name: ClassVar[str]
    #: The default Manager for query building.
    objects: ClassVar[Manager]

    # A default integer PK avoids the ambiguity of PK-less models across backends.
    id = IntegerField(primary_key=True, auto_increment=True)

    def __init__(self, **kwargs: Any) -> None:
        # Lazy creation avoids allocating empty dicts for models that never use relation caching.
        self._relation_cache: dict[str, Any] | None = None
        # _persisted distinguishes INSERT from UPDATE for all PK types (auto, UUID, string).
        self._persisted: bool = False

        for name, field in self._fields.items():
            value = None
            if name in kwargs:
                value = kwargs[name]
            elif hasattr(field, "column_name") and field.column_name in kwargs:
                value = kwargs[field.column_name]

            if value is not None:
                setattr(self, name, value)
            elif field.default is not None:
                val = field.default() if callable(field.default) else field.default
                setattr(self, name, val)
            else:
                setattr(self, name, None)

        # Leading-underscore kwargs could overwrite internal state; unknown non-private kwargs
        # support annotation columns and ad-hoc query-result data.
        known_fields = set(self._fields.keys())
        for key in kwargs:
            if key.startswith("_"):
                raise TypeError(
                    f"{self.__class__.__name__}() does not accept private "
                    f"keyword argument {key!r}. Internal attributes cannot be "
                    f"set via the constructor."
                )
            if key not in known_fields:
                # FK column_name aliases (e.g. user_id) must be recognised as known fields.
                matched_column = False
                for _fname, fobj in self._fields.items():
                    if hasattr(fobj, "column_name") and fobj.column_name == key:
                        matched_column = True
                        break
                if not matched_column:
                    # Arbitrary kwargs must not shadow existing methods or descriptors.
                    if hasattr(type(self), key) and callable(getattr(type(self), key)):
                        raise TypeError(
                            f"{self.__class__.__name__}() does not accept keyword "
                            f"argument {key!r}: would shadow an existing method."
                        )
                    setattr(self, key, kwargs[key])

        self._previous_state: dict[str, Any] = self._snapshot()

    def _set_related(self, field_name: str, obj: Any) -> None:
        """Store a loaded related object in the cache.

        Called by select_related/prefetch_related hydration.
        Lazily initializes the cache on first use.
        """
        if self._relation_cache is None:
            self._relation_cache = {}
        self._relation_cache[field_name] = obj

    def _get_related(self, field_name: str) -> Any:
        """Retrieve a cached related object.

        Returns the cached instance if available, None otherwise.
        """
        if self._relation_cache is None:
            return None
        return self._relation_cache.get(field_name)

    @property
    def content_type(self) -> str:
        """Return the content type identifier for this model (instance or class).

        Format: 'app_label.model_name' (e.g., 'auth.User').
        """
        return f"{cast('Any', self)._app_name}.{cast('Any', self)._model_name}"

    @classmethod
    def get_content_type_label(cls) -> str:
        """Return the content type identifier for this model class."""
        return f"{cast('Any', cls)._app_name}.{cast('Any', cls)._model_name}"

    def _snapshot(self) -> dict[str, Any]:
        """Capture a shallow copy of all field values.

        For FK fields, reads the raw ID value from ``__dict__`` to avoid
        the ``LazyFK`` descriptor wrapper.

        Optimized with direct __dict__ access to avoid getattr() overhead.
        """
        snap: dict[str, Any] = {}
        obj_dict = self.__dict__
        for name, field in self._fields.items():
            # M2M descriptors allocate a manager on access; skip to avoid that cost.
            if isinstance(field, ManyToManyField):
                continue
            if isinstance(field, ForeignKey):
                snap[name] = obj_dict.get(field.column_name)
            else:
                # __dict__ lookup avoids the descriptor overhead of getattr() for plain fields.
                snap[name] = obj_dict.get(name, getattr(self, name, None))
        return snap

    def _get_changed_fields(self) -> dict[str, Any]:
        """Return a dict of ``{field_name: previous_value}`` for changed fields."""
        changed: dict[str, Any] = {}
        for name, field in self._fields.items():
            # M2M descriptors allocate a manager on access; skip to avoid that cost.
            if isinstance(field, ManyToManyField):
                continue
            prev = self._previous_state.get(name)
            if isinstance(field, ForeignKey):
                curr = self.__dict__.get(field.column_name)
            else:
                curr = getattr(self, name, None)
            if prev != curr:
                changed[name] = prev
        return changed

    @property
    def has_changed(self) -> bool:
        """``True`` if any field value differs from the last-saved state."""
        return bool(self._get_changed_fields())

    async def before_validate(self) -> None:
        """Called before :meth:`validate` during both create and update."""

    async def validate(self) -> None:
        """Validate all field values using each field's ``validate()`` method.

        Collects every field-level error and raises a single
        :class:`ValueError` listing all failures.  Override in subclasses to
        add custom business-rule validation (call ``await super().validate()``
        first to keep the built-in checks).

        Fields that have been soft-removed (via migrations) are
        automatically excluded from validation.
        """

        await load_soft_removed_columns()
        soft_removed = get_soft_removed_columns(self._table_name)

        errors: list[str] = []
        for name, field in self._fields.items():
            # Auto-PKs are None before INSERT and must not trigger null-validation errors.
            if field.primary_key and field.auto_increment:
                continue
            if isinstance(field, DateTimeField) and (
                getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False)
            ):
                continue
            if field.column_name in soft_removed:
                continue
            # M2M fields lack a DB column and cannot be validated like scalar fields.
            if isinstance(field, ManyToManyField):
                continue

            value = getattr(self, name, None)

            # A FK is satisfied when either the relation object or the raw ID alias is present.
            if (
                value is None
                and not field.null
                and hasattr(field, "column_name")
                and field.column_name != name
                and getattr(self, field.column_name, None) is not None
            ):
                continue

            try:
                field.validate(value)
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        if errors:
            raise ValueError(
                f"Validation failed for {self.__class__.__name__}: " + "; ".join(errors)
            )

        # unique_together must be enforced in Python to catch violations before the DB round-trip.
        is_create = not getattr(self, "_persisted", False)
        for ut_fields in getattr(self.__class__, "_meta_unique_together", []):
            filter_kwargs: dict[str, Any] = {}
            skip = False
            for f_name in ut_fields:
                ut_field: Field | None = self._fields.get(f_name)
                col = ut_field.column_name if ut_field else f_name
                raw = self.__dict__.get(col) if ut_field else getattr(self, f_name, None)
                if raw is None:
                    skip = True
                    break
                filter_kwargs[col] = raw
            if skip or not filter_kwargs:
                continue
            qs = self.__class__.objects.filter(**filter_kwargs)
            if not is_create:
                qs = qs.exclude(id=self.id)
            if await qs.exists():
                raise ValueError(
                    f"Duplicate entry: a {self.__class__.__name__} with "
                    + ", ".join(f"{k}={v!r}" for k, v in filter_kwargs.items())
                    + " already exists."
                )

    async def before_insert(self) -> None:
        """Called only on create, after validation but before the INSERT."""

    async def before_save(self) -> None:
        """Called on both create and update, immediately before the DB write."""

    async def after_insert(self) -> None:
        """Called only on create, after the INSERT has succeeded."""

    async def on_update(self) -> None:
        """Called only on update, after the UPDATE has succeeded."""

    async def on_delete(self) -> None:
        """Called before the DELETE is issued.  Raise to abort deletion."""

    async def after_delete(self) -> None:
        """Called after a successful DELETE."""

    async def on_change(self, previous_state: dict[str, Any]) -> None:
        """Called after create or update if field values actually changed.

        Args:
            previous_state: Dict of ``{field_name: old_value}`` for every
                field that differed from the saved state.
        """

    @property
    def pk(self) -> Any:
        """Primary key (aliased to ``id`` by default)."""
        return getattr(self, "id", None)

    def _apply_auto_fields(self) -> None:
        now = timezone.now()
        for name, field in self._fields.items():
            if isinstance(field, DateTimeField) and (
                field.auto_now or (field.auto_now_add and getattr(self, name) is None)
            ):
                setattr(self, name, now)
            elif getattr(field, "auto", False) and getattr(self, name) is None:
                default = getattr(field, "default", None)
                if callable(default):
                    setattr(self, name, default())

    def _to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, field in self._fields.items():
            if isinstance(field, ManyToManyField):
                continue
            if isinstance(field, ForeignKey):
                result[field.column_name] = self.__dict__.get(field.column_name)
            else:
                result[name] = getattr(self, name, None)
        return result

    def as_dict(self, *, include_relations: bool = False) -> dict[str, Any]:
        """Return a plain ``dict`` representation of this model instance.

        All column fields are included.  ``ManyToManyField`` columns are
        skipped (they have no DB column); set *include_relations* to
        ``True`` to include any already-loaded related objects from the
        relation cache as nested dicts.

        Example::

            user = await User.objects.get(id=1)
            data = user.as_dict()
            # {"id": 1, "username": "admin", "email": "admin@example.com", ...}
        """
        result: dict[str, Any] = {}
        for name, field in self._fields.items():
            if isinstance(field, ManyToManyField):
                continue
            if isinstance(field, ForeignKey):
                raw = self.__dict__.get(field.column_name)
                result[name] = raw.fk_id if isinstance(raw, LazyFK) else raw
            else:
                result[name] = getattr(self, name, None)

        if include_relations and self._relation_cache:
            for rel_name, rel_obj in self._relation_cache.items():
                if rel_name in result:
                    continue
                if isinstance(rel_obj, Model):
                    result[rel_name] = rel_obj.as_dict()
                elif isinstance(rel_obj, list):
                    result[rel_name] = [
                        item.as_dict() if isinstance(item, Model) else item for item in rel_obj
                    ]
                else:
                    result[rel_name] = rel_obj

        return result

    def as_json(self, *, include_relations: bool = False, indent: int | None = None) -> str:
        """Return a JSON string representation of this model instance.

        Non-serialisable types (``datetime``, ``date``, ``UUID``, ``Decimal``)
        are automatically coerced to strings.  Pass *indent* for pretty-printing.

        Example::

            user = await User.objects.get(id=1)
            print(user.as_json(indent=2))
        """

        def _default(obj: Any) -> Any:
            if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
                return obj.isoformat()
            if isinstance(obj, uuid.UUID):
                return str(obj)
            if isinstance(obj, decimal.Decimal):
                return str(obj)
            if isinstance(obj, LazyFK):
                return obj.fk_id
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")

        return json.dumps(
            self.as_dict(include_relations=include_relations),
            default=_default,
            indent=indent,
        )

    @classmethod
    def _from_row(cls: type[T], row: dict[str, Any]) -> T:
        field_data = {}
        extra_data = {}
        known_columns = set()
        for name, field in cls._fields.items():
            col_name = field.column_name
            known_columns.add(col_name)
            if col_name in row:
                field_data[name] = row[col_name]
            elif name in row:
                field_data[name] = row[name]
        # Annotation and join columns are set post-construction to avoid
        # __init__ rejecting unknown kwargs.
        for key, val in row.items():
            if key not in field_data and key not in known_columns:
                extra_data[key] = val
        instance = cls(**field_data)
        for key, val in extra_data.items():
            setattr(instance, key, val)
        instance._persisted = True
        return instance

    @classmethod
    @functools.cache
    def _field_mapping(
        cls,
    ) -> tuple[
        tuple[tuple[str, str, str, bool], ...],
        frozenset[str],
        frozenset[str],
    ]:
        """Pre-compute per-model field mapping for fast hydration.

        Returns:
            (field_specs, field_names, col_names) where each field_spec is
            (field_name, col_name, dict_key, has_callable_default).
        """
        specs: list[tuple[str, str, str, bool]] = []
        field_names: set[str] = set()
        col_names: set[str] = set()
        for name, field in cls._fields.items():
            col_name = field.column_name
            dict_key = col_name if hasattr(field, "resolve_target") else name
            has_callable = field.default is not None and callable(field.default)
            specs.append((name, col_name, dict_key, has_callable))
            field_names.add(name)
            col_names.add(col_name)
        return tuple(specs), frozenset(field_names), frozenset(col_names)

    @classmethod
    def _from_row_fast(cls: type[T], row: dict[str, Any]) -> T:
        """Fast-path hydration that bypasses ``__init__`` and ``_snapshot()``.

        Uses a per-model cached field mapping to avoid per-row introspection.
        Sets ``__dict__`` directly, skipping three full field iterations
        that ``__init__`` performs (defaults, extras, snapshot).
        """
        specs, known_fields, known_cols = cls._field_mapping()

        instance = cls.__new__(cls)
        inst_dict = instance.__dict__
        prev_state: dict[str, Any] = {}
        instance._relation_cache = None
        instance._persisted = True
        instance._previous_state = prev_state

        row_get = row.get
        fields_map = cls._fields

        for field_name, col_name, dict_key, has_callable_default in specs:
            value = row_get(col_name)
            if value is not None:
                inst_dict[dict_key] = value
                prev_state[field_name] = value
            elif col_name in row:
                inst_dict[dict_key] = None
                prev_state[field_name] = None
            else:
                value = row_get(field_name)
                if value is not None:
                    inst_dict[dict_key] = value
                    prev_state[field_name] = value
                elif field_name in row:
                    inst_dict[dict_key] = None
                    prev_state[field_name] = None
                else:
                    field = fields_map[field_name]
                    if field.default is not None:
                        value = field.default() if has_callable_default else field.default
                        inst_dict[dict_key] = value
                        prev_state[field_name] = value
                    else:
                        inst_dict[dict_key] = None
                        prev_state[field_name] = None

        # Annotation columns live outside _fields; skip known keys to avoid overwriting field data.
        for key, val in row.items():
            if key not in known_fields and key not in known_cols:
                inst_dict[key] = val

        return instance

    @classmethod
    def _get_insert_statement(cls) -> Any:
        """Return a SQLAlchemy insert statement for this model's table."""

        table = get_table(cls)
        return insert(table)

    def _trigger_event(self, event_name: str, **kwargs: Any) -> None:
        """Fire MODEL_EVENTS handlers for *event_name* on this instance.

        A no-op when the task system is disabled or no handlers are registered
        for this model.  Exceptions inside individual handlers are caught and
        logged by the dispatcher - they never propagate here.

        Args:
            event_name: One of the nine lifecycle hook names (e.g.
                        ``"after_insert"``, ``"on_change"``, ``"after_delete"``).
            **kwargs:   Extra context forwarded verbatim to every handler.
        """
        try:
            model_path = f"{self.__class__.__module__}.{self.__class__.__name__}"
            dispatcher = get_dispatcher()
            if dispatcher is not None:
                # Both settings-based and decorator-based handlers fire
                # through a single dispatch point.
                dispatcher.trigger(model_path, event_name, self, **kwargs)
            else:
                # Decorator-based handlers must still fire even when the task system is off.
                dispatch_decorator_handlers(model_path, event_name, self, **kwargs)
        except Exception:
            logger.debug(
                "Model event dispatch failed for %s.%s", model_path, event_name, exc_info=True
            )
            # Persistence must never fail due to a misbehaving event handler.

    async def save(
        self,
        ignore_permissions: bool = False,
        update_fields: list[str] | None = None,
    ) -> None:
        """Persist this instance to the database (INSERT or UPDATE).

        Args:
            ignore_permissions: Skip permission checks when ``True``.
            update_fields: Optional list of field names to restrict on UPDATE.
                When supplied only those columns are written; all other fields
                are left unchanged in the database.  Ignored on INSERT.
                Raises :exc:`ValueError` for unknown field names.

                Example::

                    user.last_login = timezone.now()
                    await user.save(update_fields=["last_login"])

        Executes the full lifecycle hook chain:

        * **Create** (``pk is None``):
          ``before_validate → validate → before_insert → before_save → INSERT
          → after_insert → on_change``

        * **Update** (``pk`` set):
          ``before_validate → validate → before_save → UPDATE → on_update
          → on_change`` (only when data actually changed)
        """

        # _persisted distinguishes INSERT from UPDATE for all PK types (auto, UUID, string).
        is_create = not getattr(self, "_persisted", False)

        # Prevent a second row when save() is called directly on a
        # singleton model that bypasses Manager.create().
        if is_create and self._meta.single:
            await enforce_single_model_constraint(type(self))

        # Capture pre-save diff so on_change handlers receive the exact field-level delta.
        pre_save_state = self._get_changed_fields() if not is_create else {}

        try:
            await call_hook(self.before_validate)
            self._trigger_event("before_validate")
            await call_hook(self.validate)
            self._trigger_event("validate")

            if is_create:
                await call_hook(self.before_insert)
                self._trigger_event("before_insert")

            await call_hook(self.before_save)
            self._trigger_event("before_save")

            token = None
            if ignore_permissions:
                token = ignore_permissions_ctx.set(True)

            try:
                if self._meta.virtual:
                    if self._meta.read_only:
                        raise ReadOnlyVirtualModelError(
                            f"{self.__class__.__name__} is configured as read-only."
                        )
                    backend = backend_registry.get(self._meta.backend)
                    data = self._to_dict()
                    if is_create:
                        row = await backend.create(type(self), data)
                    else:
                        row = await backend.update(type(self), self.pk, data)
                    for key, value in row.items():
                        if key in self._fields:
                            setattr(self, key, value)
                    self._persisted = True
                else:
                    await execute_save(
                        self,
                        ignore_permissions=ignore_permissions,
                        update_fields=update_fields,
                    )

                if is_create:
                    await call_hook(self.after_insert)
                    self._trigger_event("after_insert")
                    # On creation every field is new, so the entire state is the change dict.
                    initial_state = self._to_dict()
                    await call_hook(self.on_change, initial_state)
                    self._trigger_event("on_change", change_dict=initial_state)
                else:
                    await call_hook(self.on_update)
                    self._trigger_event("on_update")
                    if pre_save_state:
                        await call_hook(self.on_change, pre_save_state)
                        self._trigger_event("on_change", change_dict=pre_save_state)
            finally:
                if token:
                    ignore_permissions_ctx.reset(token)

            # Snapshot must follow persistence so the next save() can diff
            # against the persisted state.
            self._previous_state = self._snapshot()
        except Exception as e:
            logger.error(
                "Save failed for %s (pk=%s, is_create=%s): %s",
                self.__class__.__name__,
                self.pk,
                is_create,
                str(e),
                exc_info=True,
                extra={"model": self.__class__.__name__, "pk": self.pk, "is_create": is_create},
            )
            raise

    async def delete(self, ignore_permissions: bool = False) -> None:
        """Delete this instance from the database.

        Executes: ``on_delete → DELETE → after_delete``.
        If :meth:`on_delete` raises, the DELETE is aborted.
        """

        if self._meta.single:
            raise SingleModelDeleteForbiddenError(
                f"{self.__class__.__name__} single records cannot be deleted."
            )

        try:
            await call_hook(self.on_delete)
            self._trigger_event("on_delete")
            token = None
            if ignore_permissions:
                token = ignore_permissions_ctx.set(True)

            try:
                if self._meta.virtual:
                    if self._meta.read_only:
                        raise ReadOnlyVirtualModelError(
                            f"{self.__class__.__name__} is configured as read-only."
                        )
                    await backend_registry.get(self._meta.backend).delete(type(self), self.pk)
                else:
                    await execute_delete_instance(self, ignore_permissions=ignore_permissions)
            finally:
                if token:
                    ignore_permissions_ctx.reset(token)
            await call_hook(self.after_delete)
            self._trigger_event("after_delete")
        except Exception as e:
            logger.error(
                "Delete failed for %s (pk=%s): %s",
                self.__class__.__name__,
                self.pk,
                str(e),
                exc_info=True,
                extra={"model": self.__class__.__name__, "pk": self.pk},
            )
            raise

    async def refresh_from_db(self) -> None:
        """Reload all fields from the database."""
        updated = await self.__class__.objects.get(id=self.pk)
        for name in self._fields:
            setattr(self, name, getattr(updated, name))
        self._previous_state = self._snapshot()

    async def full_clean(self) -> None:
        """Run complete validation: field-level checks plus custom model validation.

        Combines the built-in :meth:`validate` (which runs all field validators)
        with a user-overridable :meth:`clean` hook for cross-field rules.

        Override :meth:`clean` in subclasses for additional business-rule
        validation.  Raise :class:`ValueError` to report a failure.

        .. code-block:: python

            class Event(Model):
                start_at = DateTimeField()
                end_at   = DateTimeField()

                async def clean(self) -> None:
                    if self.start_at and self.end_at and self.start_at >= self.end_at:
                        raise ValueError("start_at must be before end_at")

            event = Event(start_at=..., end_at=...)
            await event.full_clean()   # raises if invalid
        """
        await call_hook(self.before_validate)
        await call_hook(self.validate)
        await call_hook(self.clean)

    async def clean(self) -> None:
        """Cross-field validation hook called by :meth:`full_clean`.

        Override in subclasses to add business-rule validation that spans
        multiple fields.  Raise :class:`ValueError` to report failures.
        The default implementation is a no-op.
        """

    def get_deferred_fields(self) -> list[str]:
        """Return a list of field names not currently loaded on this instance.

        Useful for introspecting which fields were excluded by a previous
        :meth:`~QuerySet.defer` call.
        """
        loaded = set(self.__dict__)
        deferred: list[str] = []
        for name, field in self._fields.items():
            col = field.column_name if hasattr(field, "column_name") else name
            if name not in loaded and col not in loaded:
                deferred.append(name)
        return deferred

    def __str__(self) -> str:
        pk = getattr(self, "id", None)
        return f"{self.__class__.__name__} object (pk={pk!r})"

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__} pk={pk!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.pk is not None and self.pk == other.pk

    def __hash__(self) -> int:
        pk = self.pk
        if pk is None:
            return id(self)
        return hash((self.__class__, pk))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.pk is None or other.pk is None:
            return NotImplemented
        return bool(self.pk < other.pk)

    def __le__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.pk is None or other.pk is None:
            return NotImplemented
        return bool(self.pk <= other.pk)

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.pk is None or other.pk is None:
            return NotImplemented
        return bool(self.pk > other.pk)

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.pk is None or other.pk is None:
            return NotImplemented
        return bool(self.pk >= other.pk)


# Cross-module references break the circular import between fields.py and models.py.
registry_mod.model_meta_cls = ModelMeta
registry_mod.model_cls = Model
registry_mod.queryset_cls = QuerySet


class AbstractModel(Model):
    """Abstract base model - subclasses share fields but no table is created.

    Use for common timestamp mixins:

    .. code-block:: python

        class TimestampMixin(AbstractModel):
            created_at = DateTimeField(auto_now_add=True)
            updated_at = DateTimeField(auto_now=True)

        class Post(TimestampMixin):
            title = CharField(max_length=255)
    """

    class Meta:
        abstract = True


class TextChoice(StrEnum):
    """TextChoic with value + label."""

    def __new__(cls, value: str, label: str) -> TextChoice:
        obj = str.__new__(cls, value)
        obj._value_ = value  # enum value
        obj.label = label  # human-readable label
        return obj

    @ClassProperty
    def choices(self: type[TextChoice]) -> list[tuple[str, str]]:
        return [(member.value, member.label) for member in self]

    @ClassProperty
    def values(self: type[TextChoice]) -> list[str]:
        return [member.value for member in self]

    @ClassProperty
    def labels(self: type[TextChoice]) -> list[str]:
        return [member.label for member in self]

    @ClassProperty
    def names(self: type[TextChoice]) -> list[str]:
        return [member.name for member in self]

    @classmethod
    def from_value(cls, value: str) -> TextChoice:
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"{value!r} is not a valid value for {cls.__name__}")

    @classmethod
    def from_label(cls, label: str) -> TextChoice:
        for member in cls:
            if member.label == label:
                return member
        raise ValueError(f"{label!r} is not a valid label for {cls.__name__}")
