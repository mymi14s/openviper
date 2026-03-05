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

import inspect
import re
from typing import Any, ClassVar, TypeVar, cast

from sqlalchemy import insert

from openviper.auth.permissions import check_permission_for_model
from openviper.db.connection import get_connection
from openviper.db.executor import (
    _load_soft_removed_columns,
    execute_count,
    execute_delete,
    execute_delete_instance,
    execute_save,
    execute_select,
    execute_update,
    get_soft_removed_columns,
    get_table,
)
from openviper.db.fields import DateTimeField, Field, IntegerField
from openviper.exceptions import DoesNotExist, MultipleObjectsReturned
from openviper.utils import timezone

T = TypeVar("T", bound="Model")


# ── Metaclass ─────────────────────────────────────────────────────────────────


class ModelMeta(type):
    """Metaclass that collects field definitions and wires up the Manager.

    Automatically generates table_name as {app_name}_{model_name} in snake_case
    if not explicitly specified in Meta.table_name.
    """

    registry: ClassVar[dict[str, type[Model]]] = {}

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
                table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower() + "s"
        namespace["_table_name"] = table_name

        cls = super().__new__(mcs, name, bases, namespace)

        # Attach the Manager and register with metadata
        meta = namespace.get("Meta")
        is_abstract = getattr(meta, "abstract", False) if meta else False

        if name != "Model" and not is_abstract:
            manager = Manager(cast("Any", cls))
            cls.objects = manager  # type: ignore[attr-defined]
            get_table(cast("Any", cls))
            mcs.registry[f"{app_name}.{name}"] = cast("Any", cls)

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
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ── Manager (QuerySet factory) ────────────────────────────────────────────────


class Manager:
    """Default model manager — provides queryset-factory methods.

    Access via ``Model.objects``.
    """

    def __init__(self, model_class: type[Model]) -> None:
        self.model = model_class

    def all(self) -> QuerySet:
        return QuerySet(self.model)

    def filter(self, **kwargs: Any) -> QuerySet:
        ignore_permissions = kwargs.pop("ignore_permissions", False)
        return QuerySet(self.model, ignore_permissions=ignore_permissions).filter(**kwargs)

    def exclude(self, **kwargs: Any) -> QuerySet:
        return QuerySet(self.model).exclude(**kwargs)

    def order_by(self, *fields: str) -> QuerySet:
        return QuerySet(self.model).order_by(*fields)

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

    async def bulk_create(self, objs: list[Model], ignore_permissions: bool = False) -> list[Model]:
        from openviper.core.context import ignore_permissions_ctx

        token = None
        if ignore_permissions:
            token = ignore_permissions_ctx.set(True)

        try:
            await check_permission_for_model(
                self.model, "create", ignore_permissions=ignore_permissions
            )
            conn = await get_connection()
            for obj in objs:
                obj._apply_auto_fields()
            records = [o._to_dict() for o in objs]
            async with conn.begin():
                await conn.execute(
                    self.model._get_insert_statement(),
                    records,
                )
            return objs
        finally:
            if token:
                ignore_permissions_ctx.reset(token)

    def __repr__(self) -> str:
        return f"Manager(model={self.model.__name__})"


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
        self._order: list[str] = []
        self._limit: int | None = None
        self._offset: int | None = None
        self._select_related: list[str] = []
        self._prefetch_related: list[str] = []
        self._ignore_permissions = ignore_permissions

    def filter(self, **kwargs: Any) -> QuerySet:
        ignore_permissions = kwargs.pop("ignore_permissions", None)
        clone = self._clone()
        if ignore_permissions is not None:
            clone._ignore_permissions = ignore_permissions
        clone._filters.append(kwargs)
        return clone

    def exclude(self, **kwargs: Any) -> QuerySet:
        clone = self._clone()
        clone._excludes.append(kwargs)
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

    def select_related(self, *fields: str) -> QuerySet:
        clone = self._clone()
        clone._select_related = list(fields)
        return clone

    def prefetch_related(self, *fields: str) -> QuerySet:
        clone = self._clone()
        clone._prefetch_related = list(fields)
        return clone

    async def all(self) -> list[Model]:
        from openviper.auth.permissions import PermissionError as ModelPermissionError
        from openviper.core.context import ignore_permissions_ctx

        token = None
        if self._ignore_permissions:
            token = ignore_permissions_ctx.set(True)
        try:
            await check_permission_for_model(
                self._model, "read", ignore_permissions=self._ignore_permissions
            )
            rows = await execute_select(self)
            return [self._model._from_row(row) for row in rows]
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
            results = await self.all()
        return results[-1] if results else None

    async def count(self) -> int:
        from openviper.auth.permissions import PermissionError as ModelPermissionError
        from openviper.core.context import ignore_permissions_ctx

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
        return await self.count() > 0

    async def delete(self) -> int:
        from openviper.core.context import ignore_permissions_ctx

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
        from openviper.core.context import ignore_permissions_ctx

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

    def _clone(self) -> QuerySet:
        clone = QuerySet(self._model)
        clone._filters = list(self._filters)
        clone._excludes = list(self._excludes)
        clone._order = list(self._order)
        clone._limit = self._limit
        clone._offset = self._offset
        clone._select_related = list(self._select_related)
        clone._prefetch_related = list(self._prefetch_related)
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

        # Set any extra kwargs (for subclasses that add instance attrs)
        for key, val in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, val)

        # Snapshot the initial state for change detection
        self._previous_state: dict[str, Any] = self._snapshot()

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
        """Capture a shallow copy of all field values."""
        return {name: getattr(self, name, None) for name in self._fields}

    def _get_changed_fields(self) -> dict[str, Any]:
        """Return a dict of ``{field_name: previous_value}`` for changed fields."""
        changed: dict[str, Any] = {}
        for name in self._fields:
            prev = self._previous_state.get(name)
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
        return {name: getattr(self, name, None) for name in self._fields}

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
            from openviper.tasks.events import (  # deferred; avoids circular import
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
        from openviper.core.context import ignore_permissions_ctx

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

        from openviper.core.context import ignore_permissions_ctx

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
