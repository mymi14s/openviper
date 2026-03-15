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
import inspect
import re
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Any, ClassVar, TypeVar, cast

from sqlalchemy import insert

from openviper.auth.permission_core import (
    PermissionError as ModelPermissionError,
)
from openviper.auth.permission_core import (
    check_permission_for_model,
)
from openviper.core.context import ignore_permissions_ctx
from openviper.db.executor import (
    _begin,
    _load_soft_removed_columns,
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
)
from openviper.db.fields import (
    DateTimeField,
    Field,
    ForeignKey,
    IntegerField,
    LazyFK,
    OneToOneField,
)
from openviper.exceptions import DoesNotExist, FieldError, MultipleObjectsReturned
from openviper.utils import timezone

T = TypeVar("T", bound="Model")

# Pre-compiled regex patterns for CamelCase → snake_case conversion.
_CAMEL_RE1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE2 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_RE3 = re.compile(r"(?<!^)(?=[A-Z])")

# Per-request permission-check cache: {(model, action): bool}
_perm_cache: ContextVar[dict[tuple[type, str], bool] | None] = ContextVar(
    "_perm_cache", default=None
)


async def _check_perm_cached(model: type, action: str, ignore_permissions: bool = False) -> None:
    """Check permissions with per-request caching.

    Once a (model, action) pair has been checked successfully within a
    request, subsequent calls return immediately without re-checking.
    """
    if ignore_permissions:
        return

    cache = _perm_cache.get()
    if cache is None:
        # No request context — fall through to uncached check.
        await check_permission_for_model(model, action, ignore_permissions=False)
        return

    key = (model, action)
    if key in cache:
        return  # Already verified this request.

    await check_permission_for_model(model, action, ignore_permissions=False)
    cache[key] = True


# ── Metaclass ─────────────────────────────────────────────────────────────────


class ModelMeta(type):
    """Metaclass that collects field definitions and wires up the Manager.

    Automatically generates table_name as {app_name}_{model_name} in snake_case
    if not explicitly specified in Meta.table_name.
    """

    registry: ClassVar[dict[str, type[Model]]] = {}
    # Secondary index: simple model name → list of registered classes.
    # Enables O(1) lookup in ForeignKey.resolve_target() instead of O(n) scan.
    _name_index: ClassVar[dict[str, list[type]]] = {}

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ModelMeta:
        fields: dict[str, Field] = {}

        # Collect fields from bases first
        for base in bases:
            if hasattr(base, "_fields"):
                fields.update(base._fields)

        # Collect fields from declaring class
        for attr_name, attr_val in list(namespace.items()):
            if isinstance(attr_val, Field):
                attr_val.name = attr_name
                fields[attr_name] = attr_val
                # Ensure hasattr(Model, 'field_id') works for ForeignKeys
                if hasattr(attr_val, "column_name") and attr_val.column_name != attr_name:
                    namespace[attr_val.column_name] = attr_val

        namespace["_fields"] = fields

        # Extract app name from module path (e.g., 'apps.blog.models' -> 'blog')
        app_name = mcs._extract_app_name(namespace.get("__module__", ""), name)
        namespace["_app_name"] = app_name
        namespace["_model_name"] = name

        # Determine table name: use Meta.table_name or auto-generate {app_name}_{model_name}
        meta = namespace.get("Meta")
        if meta and hasattr(meta, "table_name") and meta.table_name:
            table_name = meta.table_name
        else:
            # Auto-generate: {app_name}_{model_name} in snake_case
            model_snake = mcs._camel_to_snake(name)
            if app_name and app_name != "default" and name != "Model":
                table_name = f"{app_name}_{model_snake}".lower()
            else:
                # Fallback to pluralize snake_case for backward compatibility
                table_name = _CAMEL_RE3.sub("_", name).lower() + "s"
        namespace["_table_name"] = table_name

        cls = super().__new__(mcs, name, bases, namespace)

        # Attach the Manager and register with metadata
        meta = namespace.get("Meta")
        is_abstract = getattr(meta, "abstract", False) if meta else False

        if name != "Model" and not is_abstract:
            manager = Manager(cast("Any", cls))
            cls.objects = manager  # type: ignore[attr-defined]
            get_table(cast("Any", cls))
            registry_key = f"{app_name}.{name}"
            mcs.registry[registry_key] = cast("Any", cls)
            # Maintain simple-name index for O(1) resolve_target() lookups.
            mcs._name_index.setdefault(name, []).append(cast("Any", cls))

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

        # Handle 'apps.{app_name}.models' pattern
        if "apps" in parts:
            app_index = parts.index("apps")
            if app_index + 1 < len(parts):
                return parts[app_index + 1]

        # Handle 'openviper.{app_name}.models' pattern (built-in apps)
        if "openviper" in parts and len(parts) >= 3:
            return parts[1]  # e.g., 'auth' from 'openviper.auth.models'

        # Fallback: use second-to-last part if available
        return parts[-2] if len(parts) >= 2 else "default"

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert CamelCase to snake_case.

        Examples:
            'Post' -> 'post'
            'PostView' -> 'post_view'
            'UserFollow' -> 'user_follow'
        """
        # Insert underscore before uppercase letters (except at start)
        s1 = _CAMEL_RE1.sub(r"\1_\2", name)
        return _CAMEL_RE2.sub(r"\1_\2", s1).lower()


# ── F expression ─────────────────────────────────────────────────────────────


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


class _FExpr:
    """Arithmetic combination of F references and literals.

    Not instantiated directly — produced by F arithmetic operators.
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


# ── Aggregate expressions ────────────────────────────────────────────────────


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


# ── Q object ─────────────────────────────────────────────────────────────────


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
        # children: list of (key, value) tuples at leaf nodes,
        # or nested Q objects for compound expressions.
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
            f"Q(connector={self.connector!r}, negated={self.negated}, "
            f"children={self.children!r})"
        )


# ── Manager (QuerySet factory) ────────────────────────────────────────────────


class Manager:
    """Default model manager — provides queryset-factory methods.

    Access via ``Model.objects``.
    """

    def __init__(self, model_class: type[Model]) -> None:
        self.model = model_class

    def all(self) -> QuerySet:
        return QuerySet(self.model)

    def filter(self, *args: Any, **kwargs: Any) -> QuerySet:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        return QuerySet(self.model, ignore_permissions=ignore_permissions).filter(*args, **kwargs)

    def exclude(self, *args: Any, **kwargs: Any) -> QuerySet:
        return QuerySet(self.model).exclude(*args, **kwargs)

    def order_by(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).order_by(*fields)

    def only(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).only(*fields)

    def defer(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).defer(*fields)

    def distinct(self) -> QuerySet:
        return QuerySet(self.model).distinct()

    def annotate(self, **kwargs: Any) -> QuerySet:
        return QuerySet(self.model).annotate(**kwargs)

    def select_related(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).select_related(*fields)

    def prefetch_related(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).prefetch_related(*fields)

    async def values(self, *fields: str) -> list[dict[str, Any]]:
        return await QuerySet(self.model).values(*fields)

    async def values_list(
        self, *fields: str, flat: bool = False
    ) -> list[tuple[Any, ...]] | list[Any]:
        return await QuerySet(self.model).values_list(*fields, flat=flat)

    async def aggregate(self, **kwargs: Any) -> dict[str, Any]:
        return await QuerySet(self.model).aggregate(**kwargs)

    async def explain(self) -> str:
        return await QuerySet(self.model).explain()

    async def iterator(self, chunk_size: int = 2000) -> AsyncGenerator[Model]:
        async for inst in QuerySet(self.model).iterator(chunk_size=chunk_size):
            yield inst

    async def batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        async for batch in QuerySet(self.model).batch(size=size):
            yield batch

    async def id_batch(self, size: int = 100) -> AsyncGenerator[list[Model]]:
        async for batch in QuerySet(self.model).id_batch(size=size):
            yield batch

    async def get(self, **kwargs: Any) -> Model:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        return (
            await QuerySet(self.model, ignore_permissions=ignore_permissions).filter(**kwargs).get()
        )

    async def get_or_none(self, **kwargs: Any) -> Model | None:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        try:
            return await self.get(ignore_permissions=ignore_permissions, **kwargs)
        except DoesNotExist:
            return None

    async def create(self, **kwargs: Any) -> Model:
        instance = self.model(**kwargs)
        await instance.save()
        return instance

    async def get_or_create(
        self, defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[Model, bool]:
        try:
            obj = await self.get(**kwargs)
            return obj, False
        except DoesNotExist:
            params = {**kwargs, **(defaults or {})}
            obj = await self.create(**params)
            return obj, True

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

            # Fire pre_bulk_create event
            model_path = f"{self.model.__module__}.{self.model.__name__}"
            self._trigger_bulk_event(model_path, "pre_bulk_create", objs)

            stmt = self.model._get_insert_statement()
            if batch_size is not None and batch_size > 0:
                async with _begin() as conn:
                    for i in range(0, len(records), batch_size):
                        await conn.execute(stmt, records[i : i + batch_size])
            else:
                async with _begin() as conn:
                    await conn.execute(stmt, records)

            # Fire post_bulk_create event
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
            from openviper.db.events import _dispatch_decorator_handlers, get_dispatcher

            dispatcher = get_dispatcher()
            if dispatcher is not None:
                dispatcher.trigger(model_path, event_name, objs)
            else:
                _dispatch_decorator_handlers(model_path, event_name, objs)
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"Manager(model={self.model.__name__})"


# ── Relationship Traversal ────────────────────────────────────────────────────────


class TraversalStep:
    """Represents one step in a relationship traversal chain."""

    __slots__ = ("field_name", "field", "model_cls", "is_relation")

    def __init__(
        self, field_name: str, field: Any, model_cls: type, is_relation: bool = False
    ) -> None:
        self.field_name = field_name
        self.field = field
        self.model_cls = model_cls
        self.is_relation = is_relation  # True if field is ForeignKey

    def __repr__(self) -> str:
        return f"Step({self.field_name}: {self.model_cls.__name__})"


class TraversalLookup:
    """Parses and validates relationship traversal in filter lookups.

    Parses filter keys like "author__username" or "author__hobby__description"
    and validates the entire chain is valid, returning steps for JOIN construction.

    Example:
        >>> lookup = TraversalLookup("author__username", Blog)
        >>> lookup.parts
        # [Step(author, ForeignKey, User, True), Step(username, CharField, User, False)]
        >>> lookup.final_field  # CharField instance
    """

    __slots__ = ("key", "model_cls", "parts", "final_field", "final_model")

    def __init__(self, key: str, model_cls: type):
        self.key = key
        self.model_cls = model_cls
        self.parts: list[TraversalStep] = []
        self.final_field: Any = None
        self.final_model: type | None = None
        self._parse()

    def _parse(self) -> None:
        """Parse and validate the traversal path."""
        parts = self.key.split("__")
        current_model = self.model_cls
        current_steps = []

        # Process all but the last part (which is the final field)
        for _i, part in enumerate(parts[:-1]):
            if not hasattr(current_model, "_fields"):
                raise FieldError(f"Cannot traverse through {current_model.__name__}: not a Model")

            field = current_model._fields.get(part)
            if field is None:
                raise FieldError(f"Field '{part}' not found on {current_model.__name__}")

            # Only FK and O2O fields can be traversed
            if not isinstance(field, (ForeignKey, OneToOneField)):
                raise FieldError(
                    f"Cannot traverse through non-relationship field '{part}' "
                    f"(type: {type(field).__name__}) on {current_model.__name__}"
                )

            # Resolve the target model
            target_model = field.resolve_target()
            if target_model is None:
                raise FieldError(
                    f"Cannot resolve target model for field '{part}' on {current_model.__name__}"
                )

            # Add this step
            current_steps.append(TraversalStep(part, field, current_model, is_relation=True))
            current_model = target_model

        # Process the final field (the lookup target)
        if not hasattr(current_model, "_fields"):
            raise FieldError(f"Cannot access field on {current_model.__name__}: not a Model")

        final_field_name = parts[-1]
        final_field = current_model._fields.get(final_field_name)
        if final_field is None:
            raise FieldError(f"Field '{final_field_name}' not found on {current_model.__name__}")

        current_steps.append(
            TraversalStep(final_field_name, final_field, current_model, is_relation=False)
        )

        self.parts = current_steps
        self.final_field = final_field
        self.final_model = current_model

    def is_simple_field(self) -> bool:
        """Check if this is a simple field lookup (no FK traversal)."""
        return len(self.parts) == 1

    def get_joins_needed(self) -> list[TraversalStep]:
        """Return the FK traversal steps (all but the final field)."""
        return self.parts[:-1]

    def __repr__(self) -> str:
        return f"TraversalLookup({self.key})"


# ── QuerySet ──────────────────────────────────────────────────────────────────


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
        self._order: list[str] = []
        self._limit: int | None = None
        self._offset: int | None = None
        self._distinct: bool = False
        self._select_related: list[str] = []
        self._prefetch_related: list[str] = []
        self._ignore_permissions = ignore_permissions
        self._only_fields: list[str] = []
        self._defer_fields: list[str] = []
        self._annotations: dict[str, Any] = {}

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
        ``only()`` — the last call wins.

        .. code-block:: python

           posts = await Post.objects.defer("body", "raw_html").all()
        """
        clone = self._clone()
        clone._defer_fields = list(fields)
        clone._only_fields = []
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

    async def all(self) -> list[Model]:
        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await _check_perm_cached(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            rows = await execute_select(self)
            # Strip select_related prefixed keys before hydrating the main model
            sr_prefixes = tuple(f"{fn}__" for fn in self._select_related)
            instances: list[Model] = []

            if self._select_related:
                # Pre-compute column mappings for each related field once.
                sr_mappings: dict[str, tuple[type, list[tuple[str, str]]]] = {}
                for field_name in self._select_related:
                    field = self._model._fields.get(field_name)
                    if field is None or not hasattr(field, "resolve_target"):
                        continue
                    related_cls = cast("Any", field).resolve_target()
                    if related_cls is None:
                        continue
                    prefix = f"{field_name}__"
                    # Build mapping of (prefixed_key, unprefixed_key) pairs.
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
            reversed_order = [f[1:] if f.startswith("-") else f"-{f}" for f in self._order]
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
            await _check_perm_cached(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
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
            return await execute_values(self, fields or None)
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
        if flat:
            key = fields[0]
            return [row[key] for row in rows]
        keys = fields if fields else rows[0].keys()
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
        return await execute_explain(self)

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
        written concurrently — rows inserted during iteration cannot shift
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
                related_instance = related_cls._from_row_fast(related_row)  # type: ignore[attr-defined]
                instance._set_related(field_name, related_instance)
            else:
                instance._set_related(field_name, None)

    async def _do_prefetch_related(self, instances: list[Model]) -> None:
        """Batch-load prefetch_related FK fields and attach them to *instances*.

        Collects all FK values from the main instances, issues queries in parallel
        (one ``id__in`` query per field using asyncio.gather), and sets the related
        objects as attributes on each instance — converting FK integer IDs to model
        instances in-place. Also caches for descriptor access.
        """
        # Collect all prefetch tasks to execute in parallel
        prefetch_tasks = []
        prefetch_metadata = []  # Store (field_name, field, related_cls, fk_col, fk_ids)

        for field_name in self._prefetch_related:
            field = self._model._fields.get(field_name)
            if field is None or not hasattr(field, "resolve_target"):
                continue
            related_cls = cast("Any", field).resolve_target()
            if related_cls is None:
                continue
            # FK value is stored under the column name in __dict__
            fk_col = field.column_name if isinstance(field, ForeignKey) else field_name
            is_fk = isinstance(field, ForeignKey)

            # Collect all FK IDs in a single pass using a set comprehension
            def _extract_id(
                inst: Any, _fk_col: str = fk_col, _is_fk: bool = is_fk, _fname: str = field_name
            ) -> int | None:
                val = inst.__dict__.get(_fk_col) if _is_fk else getattr(inst, _fname, None)
                if isinstance(val, int):
                    return val
                if isinstance(val, LazyFK) and isinstance(val.fk_id, int):
                    return val.fk_id
                return None

            fk_ids = [pk for pk in (_extract_id(inst) for inst in instances) if pk is not None]
            if not fk_ids:
                continue

            # Create query task and store metadata
            prefetch_tasks.append(related_cls.objects.filter(id__in=fk_ids).all())
            prefetch_metadata.append((field_name, field, related_cls, fk_col, fk_ids))

        # Execute all prefetch queries in parallel
        if not prefetch_tasks:
            return

        prefetch_results = await asyncio.gather(*prefetch_tasks)

        # Map results back to instances
        for i, (field_name, field, _related_cls, fk_col, _fk_ids) in enumerate(prefetch_metadata):
            related_instances = prefetch_results[i]
            related_map: dict[Any, Any] = {ri.pk: ri for ri in related_instances}
            for inst in instances:
                fk_val = (
                    inst.__dict__.get(fk_col)
                    if isinstance(field, ForeignKey)
                    else getattr(inst, field_name, None)
                )
                if isinstance(fk_val, int):
                    related_obj = related_map.get(fk_val)
                    # Cache the related instance
                    inst._set_related(field_name, related_obj)
                elif isinstance(fk_val, LazyFK) and isinstance(fk_val.fk_id, int):
                    related_obj = related_map.get(fk_val.fk_id)
                    inst._set_related(field_name, related_obj)

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
        clone = QuerySet(self._model)
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
        return clone

    def __repr__(self) -> str:
        return f"QuerySet(model={self._model.__name__}, filters={self._filters})"


# ── Model ─────────────────────────────────────────────────────────────────────


# ── Hook caller ───────────────────────────────────────────────────────────────


async def _call_hook(hook: Any, *args: Any) -> Any:
    """Call a lifecycle hook, tolerating both sync and async implementations.

    If a subclass overrides a hook as a plain ``def`` instead of ``async def``,
    we still call it safely without raising ``TypeError``.
    """
    result = hook(*args)
    if inspect.isawaitable(result):
        return await result
    return result


# ── Model ─────────────────────────────────────────────────────────────────────


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

    # Every model gets a default integer primary key unless overridden
    id = IntegerField(primary_key=True, auto_increment=True)

    def __init__(self, **kwargs: Any) -> None:
        # Initialize relation cache as None for lazy creation (saves memory for
        # models without select_related/prefetch_related usage)
        self._relation_cache: dict[str, Any] | None = None

        # Set defaults from field definitions
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

        # Set any extra kwargs (for subclasses that add instance attrs).
        # Reject any kwargs beginning with '_' to prevent callers from
        # overwriting internal state such as _relation_cache or _previous_state.
        for key, val in kwargs.items():
            if key.startswith("_"):
                raise TypeError(
                    f"{self.__class__.__name__}() does not accept private "
                    f"keyword argument {key!r}. Internal attributes cannot be "
                    f"set via the constructor."
                )
            if not hasattr(self, key):
                setattr(self, key, val)

        # Snapshot the initial state for change detection
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

    # ── Change detection ──────────────────────────────────────────────────

    def _snapshot(self) -> dict[str, Any]:
        """Capture a shallow copy of all field values.

        For FK fields, reads the raw ID value from ``__dict__`` to avoid
        the ``LazyFK`` descriptor wrapper.

        Optimized with direct __dict__ access to avoid getattr() overhead.
        """
        snap: dict[str, Any] = {}
        obj_dict = self.__dict__
        for name, field in self._fields.items():
            if isinstance(field, ForeignKey):
                snap[name] = obj_dict.get(field.column_name)
            else:
                # Direct __dict__ access is faster than getattr() for simple fields
                snap[name] = obj_dict.get(name, getattr(self, name, None))
        return snap

    def _get_changed_fields(self) -> dict[str, Any]:
        """Return a dict of ``{field_name: previous_value}`` for changed fields."""
        changed: dict[str, Any] = {}
        for name, field in self._fields.items():
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

    # ── Lifecycle hooks (override in subclasses) ──────────────────────────

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

        await _load_soft_removed_columns()
        soft_removed = get_soft_removed_columns(self._table_name)

        errors: list[str] = []
        for name, field in self._fields.items():
            # Skip auto-generated PKs — they may legitimately be None before INSERT
            if field.primary_key and field.auto_increment:
                continue
            # Skip auto-managed datetime fields
            if isinstance(field, DateTimeField) and (
                getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False)
            ):
                continue
            # Skip soft-removed columns
            if field.column_name in soft_removed:
                continue

            value = getattr(self, name, None)

            # For ForeignKeys, consider valid if either relation or ID alias is set
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

    # ── Internal helpers ──────────────────────────────────────────────────

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

    def _to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, field in self._fields.items():
            if isinstance(field, ForeignKey):
                result[name] = self.__dict__.get(field.column_name)
            else:
                result[name] = getattr(self, name, None)
        return result

    @classmethod
    def _from_row(cls: type[T], row: dict[str, Any]) -> T:
        # Remap column names to field names
        field_data = {}
        for name, field in cls._fields.items():
            col_name = field.column_name
            if col_name in row:
                field_data[name] = row[col_name]
            elif name in row:
                field_data[name] = row[name]
        # Also include any extra columns not explicitly in fields
        for key, val in row.items():
            if key not in field_data:
                field_data[key] = val
        return cls(**field_data)

    @classmethod
    def _from_row_fast(cls: type[T], row: dict[str, Any]) -> T:
        """Fast-path hydration that bypasses ``__init__`` and ``_snapshot()``.

        Used for read-only query results where change-detection is not needed.
        Sets ``__dict__`` directly, avoiding three full field iterations that
        the normal ``__init__`` performs (defaults, extras, snapshot).
        """
        instance = cls.__new__(cls)
        instance._relation_cache = None  # Lazy initialization
        instance._previous_state = {}

        # Remap column names → field names directly into __dict__.
        for name, field in cls._fields.items():
            col_name = field.column_name
            # ForeignKeys store their raw IDs under column_name (e.g., 'author_id')
            # Regular fields store their values under name (e.g., 'title')
            dict_key = col_name if hasattr(field, "resolve_target") else name

            if col_name in row:
                instance.__dict__[dict_key] = row[col_name]
            elif name in row:
                instance.__dict__[dict_key] = row[name]
            else:
                # Apply default if present, else None.
                if field.default is not None:
                    instance.__dict__[dict_key] = (
                        field.default() if callable(field.default) else field.default
                    )
                else:
                    instance.__dict__[dict_key] = None

        # Extra columns (e.g. annotations) not in _fields.
        field_names = set(cls._fields)
        col_names = {f.column_name for f in cls._fields.values()}
        for key, val in row.items():
            if key not in field_names and key not in col_names:
                instance.__dict__[key] = val

        return instance

    @classmethod
    def _get_insert_statement(cls) -> Any:
        """Return a SQLAlchemy insert statement for this model's table."""

        table = get_table(cls)
        return insert(table)

    def _trigger_event(self, event_name: str) -> None:
        """Fire MODEL_EVENTS handlers for *event_name* on this instance.

        A no-op when the task system is disabled or no handlers are registered
        for this model.  Exceptions inside individual handlers are caught and
        logged by the dispatcher — they never propagate here.

        Args:
            event_name: One of the nine lifecycle hook names (e.g.
                        ``"after_insert"``, ``"on_change"``, ``"after_delete"``).
        """
        try:
            from openviper.db.events import (  # deferred; avoids circular import
                _dispatch_decorator_handlers,
                get_dispatcher,
            )

            model_path = f"{self.__class__.__module__}.{self.__class__.__name__}"
            dispatcher = get_dispatcher()
            if dispatcher is not None:
                # Settings-based handlers (MODEL_EVENTS) + decorator handlers
                # are both dispatched inside dispatcher.trigger().
                dispatcher.trigger(model_path, event_name, self)
            else:
                # Task system disabled — still fire @model_event.trigger() handlers.
                _dispatch_decorator_handlers(model_path, event_name, self)
        except Exception:
            pass  # never let event dispatch break model persistence

    async def save(self, ignore_permissions: bool = False) -> None:
        """Persist this instance to the database (INSERT or UPDATE).

        Executes the full lifecycle hook chain:

        * **Create** (``pk is None``):
          ``before_validate → validate → before_insert → before_save → INSERT
          → after_insert → on_change``

        * **Update** (``pk`` set):
          ``before_validate → validate → before_save → UPDATE → on_update
          → on_change`` (only when data actually changed)
        """

        is_create = self.pk is None

        # Capture pre-save state for on_change detection
        pre_save_state = self._get_changed_fields() if not is_create else {}

        # ── Validation phase ──────────────────────────────────────────
        await _call_hook(self.before_validate)
        self._trigger_event("before_validate")
        await _call_hook(self.validate)
        self._trigger_event("validate")

        if is_create:
            await _call_hook(self.before_insert)
            self._trigger_event("before_insert")

        await _call_hook(self.before_save)
        self._trigger_event("before_save")

        # ── Persistence ───────────────────────────────────────────────
        token = None
        if ignore_permissions:
            token = ignore_permissions_ctx.set(True)

        try:
            await execute_save(self, ignore_permissions=ignore_permissions)

            # ── Post-persistence hooks ────────────────────────────────────
            if is_create:
                await _call_hook(self.after_insert)
                self._trigger_event("after_insert")
                # For a brand-new row every field is "changed"
                changed = dict.fromkeys(self._fields)
                await _call_hook(self.on_change, changed)
                self._trigger_event("on_change")
            else:
                await _call_hook(self.on_update)
                self._trigger_event("on_update")
                if pre_save_state:
                    await _call_hook(self.on_change, pre_save_state)
                    self._trigger_event("on_change")
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

        # Reset the snapshot so subsequent saves detect new changes
        self._previous_state = self._snapshot()

    async def delete(self, ignore_permissions: bool = False) -> None:
        """Delete this instance from the database.

        Executes: ``on_delete → DELETE → after_delete``.
        If :meth:`on_delete` raises, the DELETE is aborted.
        """

        await _call_hook(self.on_delete)
        self._trigger_event("on_delete")
        token = None
        if ignore_permissions:
            token = ignore_permissions_ctx.set(True)

        try:
            await execute_delete_instance(self, ignore_permissions=ignore_permissions)
        finally:
            if token:
                ignore_permissions_ctx.reset(token)
        await _call_hook(self.after_delete)
        self._trigger_event("after_delete")

    async def refresh_from_db(self) -> None:
        """Reload all fields from the database."""
        updated = await self.__class__.objects.get(id=self.pk)
        for name in self._fields:
            setattr(self, name, getattr(updated, name))
        # Re-snapshot after refresh
        self._previous_state = self._snapshot()

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__} pk={pk!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.pk is not None and self.pk == other.pk


# ── Abstract Model ────────────────────────────────────────────────────────────


class AbstractModel(Model):
    """Abstract base model — subclasses share fields but no table is created.

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
