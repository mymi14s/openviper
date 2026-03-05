"""Low-level SQL execution helpers used by the ORM layer."""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa

from openviper.auth.permissions import check_permission_for_model
from openviper.conf import settings
from openviper.db.connection import get_engine, get_metadata
from openviper.db.fields import (
    BigIntegerField,
    BinaryField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    FileField,
    FloatField,
    ForeignKey,
    IntegerField,
    JSONField,
    OneToOneField,
    TimeField,
    UUIDField,
)
from openviper.db.migrations.executor import _get_soft_removed_table

if TYPE_CHECKING:
    from openviper.db.models import Model, QuerySet

# ---------------------------------------------------------------------------
# Soft-removed column cache (lock-free reads after write, frozenset values)
# ---------------------------------------------------------------------------

# Values are frozenset so callers can read them without holding the lock.
_SOFT_REMOVED_CACHE: dict[str, frozenset[str]] = {}
_SOFT_REMOVED_LOADED: bool = False
_soft_removed_lock: asyncio.Lock | None = None


def _get_soft_removed_lock() -> asyncio.Lock:
    """Return the module-level soft-removed lock, creating it lazily."""
    global _soft_removed_lock
    if _soft_removed_lock is None:
        _soft_removed_lock = asyncio.Lock()
    return _soft_removed_lock


async def _load_soft_removed_columns() -> None:
    """Load soft-removed column info from the tracking table into cache.

    Uses double-checked locking: the fast path checks ``_SOFT_REMOVED_LOADED``
    without acquiring the lock.  Only when the flag is ``False`` do we acquire
    and re-check inside the lock.
    """
    global _SOFT_REMOVED_LOADED

    # Fast path — already loaded, no lock needed.
    if _SOFT_REMOVED_LOADED:
        return

    lock = _get_soft_removed_lock()
    async with lock:
        if _SOFT_REMOVED_LOADED:
            return
        try:
            engine = await get_engine()
            soft_table = _get_soft_removed_table()
            async with engine.connect() as conn:
                exists = await conn.run_sync(
                    lambda sync_conn: sa.inspect(sync_conn).has_table(soft_table.name)
                )
                if not exists:
                    _SOFT_REMOVED_LOADED = True
                    return
                result = await conn.execute(
                    sa.select(soft_table.c.table_name, soft_table.c.column_name)
                )
                # Collect into a regular dict first, then convert to frozensets
                # so all writes happen atomically before the cache is updated.
                staging: dict[str, set[str]] = {}
                for row in result:
                    staging.setdefault(row.table_name, set()).add(row.column_name)
                for tname, cols in staging.items():
                    _SOFT_REMOVED_CACHE[tname] = frozenset(cols)
            _SOFT_REMOVED_LOADED = True
        except Exception:
            # If the tracking table doesn't exist yet, treat as empty.
            _SOFT_REMOVED_LOADED = True


def invalidate_soft_removed_cache() -> None:
    """Clear the soft-removed column cache (call after migrations)."""
    global _SOFT_REMOVED_LOADED
    _SOFT_REMOVED_CACHE.clear()
    _SOFT_REMOVED_LOADED = False
    _build_table.cache_clear()


def get_soft_removed_columns(table_name: str) -> frozenset[str]:
    """Return the frozenset of soft-removed column names for a table (sync).

    Must call ``_load_soft_removed_columns()`` first in an async context.
    Values are ``frozenset`` so callers can iterate without holding any lock.
    """
    return _SOFT_REMOVED_CACHE.get(table_name, frozenset())


# ---------------------------------------------------------------------------
# Table registration
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=256)
def _build_table(table_name: str, model_cls: type) -> sa.Table:
    """Build and register a SQLAlchemy Table for *model_cls*.

    Keyed by ``(table_name, model_cls)``; the LRU cache replaces the old
    unbounded ``_TABLE_CACHE`` dict and ensures each ``(name, cls)`` pair
    is only ever built once.  Building the same table twice would raise a
    SQLAlchemy ``InvalidRequestError`` (table already in metadata).
    """
    metadata = get_metadata()
    columns: list[sa.Column[Any]] = []
    added_columns: set[str] = set()
    for _name, field in cast("Any", model_cls)._fields.items():
        if field._column_type == "":
            continue  # ManyToMany — no column

        col_name = field.column_name
        if col_name in added_columns:
            continue

        col_type = _sa_type(field)
        args: list[Any] = [col_name, col_type]

        # Add ForeignKey constraint if applicable
        if isinstance(field, (ForeignKey, OneToOneField)):
            related_table = ""
            target_model_cls = field.resolve_target()

            if target_model_cls and hasattr(target_model_cls, "_table_name"):
                related_table = str(target_model_cls._table_name)
            else:
                target_str = field.to
                if callable(target_str):
                    try:
                        res = target_str()
                        if isinstance(res, type):
                            target_model_cls = res
                    except Exception:
                        pass

                if target_model_cls:
                    related_table = getattr(target_model_cls, "_table_name", "")
                elif isinstance(target_str, str):
                    from openviper.db.models import ModelMeta

                    if "." in target_str:
                        parts = target_str.split(".")
                        app_name = parts[0]
                        model_name = parts[-1]
                        model_snake = ModelMeta._camel_to_snake(model_name)

                        if model_name == "get_user_model":
                            if "auth" in parts:
                                related_table = "auth_users"
                        else:
                            related_table = f"{app_name}_{model_snake}".lower()
                    else:
                        model_snake = ModelMeta._camel_to_snake(target_str)
                        app_name = getattr(model_cls, "_app_name", "default")

                        if app_name and app_name != "default":
                            related_table = f"{app_name}_{model_snake}s".lower()
                        else:
                            related_table = f"{model_snake}s".lower()

            if related_table:
                # Final pluralization check for standard auth models
                if related_table == "auth_role":
                    related_table = "auth_roles"
                elif related_table == "auth_user":
                    related_table = "auth_users"
                elif related_table == "auth_permission":
                    related_table = "auth_permissions"

                args.append(sa.ForeignKey(f"{related_table}.id", ondelete=field.on_delete))

        col_kwargs: dict[str, Any] = {
            "nullable": field.null,
            "unique": field.unique,
            "index": field.db_index,
        }
        if field.primary_key:
            col_kwargs["primary_key"] = True
        if field.auto_increment and field.primary_key:
            col_kwargs["autoincrement"] = True
        if field.default is not None and not callable(field.default):
            col_kwargs["default"] = field.default

        col = sa.Column(*args, **col_kwargs)
        columns.append(col)
        added_columns.add(col_name)

    return sa.Table(table_name, metadata, *columns, extend_existing=True)


def get_table(model_cls: type[Model]) -> sa.Table:
    """Return (or lazily build) the SQLAlchemy Table for a model class."""
    return _build_table(model_cls._table_name, model_cls)


def _sa_type(field: Any) -> sa.types.TypeEngine[Any]:
    if isinstance(field, BinaryField):
        return sa.LargeBinary()
    if isinstance(field, (ForeignKey, OneToOneField)):
        return sa.Integer()
    if isinstance(field, BigIntegerField):
        return sa.BigInteger()
    if isinstance(field, IntegerField):
        return sa.Integer()
    if isinstance(field, FloatField):
        return sa.Float()
    if isinstance(field, DecimalField):
        return sa.Numeric(precision=field.max_digits, scale=field.decimal_places)
    if isinstance(field, BooleanField):
        return sa.Boolean()
    if isinstance(field, DateTimeField):
        return sa.DateTime(timezone=settings.USE_TZ)
    if isinstance(field, DateField):
        return sa.Date()
    if isinstance(field, TimeField):
        return sa.Time()
    if isinstance(field, UUIDField):
        return sa.String(36)
    if isinstance(field, JSONField):
        return sa.JSON()
    if isinstance(field, FileField):
        return sa.String(field.max_length)
    if isinstance(field, CharField):
        return sa.String(field.max_length)
    return sa.Text()


# ---------------------------------------------------------------------------
# Filter compiler
# ---------------------------------------------------------------------------


def _compile_filters(
    table: sa.Table, filter_dicts: list[dict[str, Any]]
) -> sa.ColumnElement[Any] | None:
    """Convert ORM filters to SQLAlchemy where clauses.

    Supports: ``field=val``, ``field__exact``, ``field__contains``,
    ``field__icontains``, ``field__startswith``, ``field__endswith``,
    ``field__gt``, ``field__gte``, ``field__lt``, ``field__lte``,
    ``field__in``, ``field__isnull``.
    """
    clauses: list[sa.ColumnElement[Any]] = []
    for filters in filter_dicts:
        for key, value in filters.items():
            parts = key.split("__", 1)
            col_name = parts[0]
            lookup = parts[1] if len(parts) > 1 else "exact"

            # Support FK _id column aliases
            if col_name not in table.c and f"{col_name}_id" in table.c:
                col_name = f"{col_name}_id"

            if col_name not in table.c:
                continue

            col = table.c[col_name]

            if lookup == "exact":
                clauses.append(col == value)
            elif lookup == "contains":
                clauses.append(col.like(f"%{value}%"))
            elif lookup == "icontains":
                clauses.append(col.ilike(f"%{value}%"))
            elif lookup == "startswith":
                clauses.append(col.like(f"{value}%"))
            elif lookup == "endswith":
                clauses.append(col.like(f"%{value}"))
            elif lookup == "gt":
                clauses.append(col > value)
            elif lookup == "gte":
                clauses.append(col >= value)
            elif lookup == "lt":
                clauses.append(col < value)
            elif lookup == "lte":
                clauses.append(col <= value)
            elif lookup == "in":
                clauses.append(col.in_(value))
            elif lookup == "isnull":
                clauses.append(col.is_(None) if value else col.isnot(None))
            elif lookup == "range":
                lo, hi = value
                clauses.append(col.between(lo, hi))
            else:
                clauses.append(col == value)

    return sa.and_(*clauses) if clauses else None


def _compile_excludes(
    table: sa.Table, exclude_dicts: list[dict[str, Any]]
) -> sa.ColumnElement[Any] | None:
    filters_clause = _compile_filters(table, exclude_dicts)
    if filters_clause is None:
        return None
    return sa.not_(filters_clause)


# ---------------------------------------------------------------------------
# Execute helpers
# ---------------------------------------------------------------------------


async def execute_select(qs: QuerySet) -> list[dict[str, Any]]:
    await check_permission_for_model(qs._model, "read", ignore_permissions=qs._ignore_permissions)

    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(table)

    where_parts: list[sa.ColumnElement[Any]] = []
    f = _compile_filters(table, qs._filters)
    if f is not None:
        where_parts.append(f)
    e = _compile_excludes(table, qs._excludes)
    if e is not None:
        where_parts.append(e)
    if where_parts:
        stmt = stmt.where(sa.and_(*where_parts))

    for field_name in qs._order:
        desc = field_name.startswith("-")
        col_name = field_name.lstrip("-")
        if col_name in table.c:
            col = table.c[col_name]
            stmt = stmt.order_by(col.desc() if desc else col.asc())

    if qs._limit is not None:
        stmt = stmt.limit(qs._limit)
    if qs._offset is not None:
        stmt = stmt.offset(qs._offset)

    engine = await get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        return [dict(row) for row in result.mappings()]


async def execute_count(qs: QuerySet) -> int:
    await check_permission_for_model(qs._model, "read", ignore_permissions=qs._ignore_permissions)

    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(sa.func.count()).select_from(table)

    where_parts: list[sa.ColumnElement[Any]] = []
    f = _compile_filters(table, qs._filters)
    if f is not None:
        where_parts.append(f)
    e = _compile_excludes(table, qs._excludes)
    if e is not None:
        where_parts.append(e)
    if where_parts:
        stmt = stmt.where(sa.and_(*where_parts))

    engine = await get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        return result.scalar_one()


async def execute_delete(qs: QuerySet) -> int:
    await check_permission_for_model(qs._model, "delete", ignore_permissions=qs._ignore_permissions)

    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.delete(table)

    where_parts: list[sa.ColumnElement[Any]] = []
    f = _compile_filters(table, qs._filters)
    if f is not None:
        where_parts.append(f)
    if where_parts:
        stmt = stmt.where(sa.and_(*where_parts))

    engine = await get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(stmt)
        return result.rowcount


async def execute_update(qs: QuerySet, values: dict[str, Any]) -> int:
    await check_permission_for_model(qs._model, "update", ignore_permissions=qs._ignore_permissions)

    model_cls = qs._model
    table = get_table(model_cls)

    field_defs = model_cls._fields
    db_values: dict[str, Any] = {}
    for k, v in values.items():
        if k in field_defs:
            db_values[field_defs[k].column_name] = field_defs[k].to_db(v)
        else:
            db_values[k] = v

    stmt = sa.update(table).values(**db_values)

    where_parts: list[sa.ColumnElement[Any]] = []
    f = _compile_filters(table, qs._filters)
    if f is not None:
        where_parts.append(f)
    if where_parts:
        stmt = stmt.where(sa.and_(*where_parts))

    engine = await get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(stmt)
        return result.rowcount


async def execute_save(instance: Model, ignore_permissions: bool = False) -> None:
    """INSERT or UPDATE a single model instance."""
    model_cls = type(instance)
    action = "update" if getattr(instance, "pk", None) else "create"
    await check_permission_for_model(model_cls, action, ignore_permissions=ignore_permissions)

    table = get_table(model_cls)
    instance._apply_auto_fields()

    # Load soft-removed columns so we can skip them during save.
    await _load_soft_removed_columns()
    soft_removed = get_soft_removed_columns(model_cls._table_name)

    data = {}
    for name, field in model_cls._fields.items():
        if field.primary_key and field.auto_increment and getattr(instance, name) is None:
            continue
        if field.column_name in soft_removed:
            continue
        data[field.column_name] = field.to_db(getattr(instance, name))

    engine = await get_engine()
    pk_val = getattr(instance, "id", None)

    if pk_val is None:
        stmt = sa.insert(table).values(**data)
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            instance.id = cast("Any", result).inserted_primary_key[0]
    else:
        upd_stmt = sa.update(table).where(table.c.id == pk_val).values(**data)
        async with engine.begin() as conn:
            await conn.execute(upd_stmt)


async def execute_delete_instance(instance: Model, ignore_permissions: bool = False) -> None:
    """Delete a single model instance by primary key."""
    model_cls = type(instance)
    await check_permission_for_model(model_cls, "delete", ignore_permissions=ignore_permissions)

    table = get_table(model_cls)
    pk_val = instance.id

    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.delete(table).where(table.c.id == pk_val))
