"""Low-level SQL execution helpers used by the ORM layer."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa

from openviper.auth.permission_core import check_permission_for_model
from openviper.conf import settings
from openviper.db.connection import _request_conn, get_engine, get_metadata
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
    LazyFK,
    OneToOneField,
    TimeField,
    UUIDField,
)
from openviper.db.migrations.executor import _get_soft_removed_table
from openviper.exceptions import FieldError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openviper.db.models import Model, QuerySet

# ---------------------------------------------------------------------------
# Global row limit to prevent memory exhaustion
# ---------------------------------------------------------------------------

# Maximum rows returned by execute_select without explicit limit.
# Prevents DoS attacks via unlimited queries on large tables.
# Can be overridden in settings with MAX_QUERY_ROWS.
# Default is 1,000 rows (conservative limit to prevent memory exhaustion).
_MAX_QUERY_ROWS_SETTING = getattr(settings, "MAX_QUERY_ROWS", 1_000)
_MAX_QUERY_ROWS_HARD_CAP = 100_000  # Absolute maximum regardless of settings
MAX_QUERY_ROWS = min(_MAX_QUERY_ROWS_SETTING, _MAX_QUERY_ROWS_HARD_CAP)

# ---------------------------------------------------------------------------
# Permission bypass context variable
# ---------------------------------------------------------------------------

# ContextVar that, when True, bypasses permission checks for the current task.
# Use bypass_permissions() context manager to set this for a scoped block.
# This is safer than passing ignore_permissions=True everywhere because it's
# explicitly scoped and cannot be accidentally left enabled.
_bypass_permissions: ContextVar[bool] = ContextVar("_bypass_permissions", default=False)


@contextlib.contextmanager
def bypass_permissions() -> Generator[None]:
    """Context manager for temporarily bypassing permission checks.

    USE WITH EXTREME CAUTION. Only for trusted internal system operations
    such as migrations, auth backends, or fixture loading. Never expose this
    to user-controlled code paths.

    Example::

        with bypass_permissions():
            await user.save()          # Permission check skipped
            await sensitive.delete()   # Permission check skipped
        # Permissions enforced again here
    """
    token = _bypass_permissions.set(True)
    try:
        yield
    finally:
        _bypass_permissions.reset(token)


# ---------------------------------------------------------------------------
# Soft-removed column cache (lock-free reads after write, frozenset values)
# ---------------------------------------------------------------------------

# Values are frozenset so callers can read them without holding the lock.
_SOFT_REMOVED_CACHE: dict[str, frozenset[str]] = {}
_SOFT_REMOVED_LOADED: bool = False
_soft_removed_lock: asyncio.Lock | None = None

# ---------------------------------------------------------------------------
# TraversalLookup cache — parse each (key, model) pair at most once
# ---------------------------------------------------------------------------

# Sentinel stored in cache when a lookup failed, so we don't
# re-raise FieldError (and re-construct TraversalLookup) on every query.
_TRAVERSAL_FAILURE: object = object()


@functools.lru_cache(maxsize=1024)
def _parse_traversal_cached(key: str, model_cls: type) -> Any:
    """Internal cached parser that returns TraversalLookup or _TRAVERSAL_FAILURE.

    LRU cache with maxsize=1024 prevents unbounded memory growth.
    """
    from openviper.db.models import TraversalLookup

    try:
        return TraversalLookup(key, model_cls)
    except FieldError:
        # Cache the failure sentinel so we don't retry parsing
        return _TRAVERSAL_FAILURE


def _cached_traversal_lookup(key: str, model_cls: type) -> Any:
    """Return a cached TraversalLookup for *(key, model_cls)*.

    Caches both successful lookups and failures (via _TRAVERSAL_FAILURE
    sentinel) so that FieldError is only constructed once per unique
    *(key, model_cls)* pair.

    Raises FieldError if the traversal is invalid.
    """
    result = _parse_traversal_cached(key, model_cls)
    if result is _TRAVERSAL_FAILURE:

        raise FieldError(key)
    return result


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _connect() -> AsyncGenerator[Any]:
    """Yield a read connection, reusing a per-request connection if active."""
    req = _request_conn.get()
    if req is not None:
        yield req
    else:
        engine = await get_engine()
        async with engine.connect() as conn:
            yield conn


@asynccontextmanager
async def _begin() -> AsyncGenerator[Any]:
    """Yield a write connection inside a transaction."""
    req = _request_conn.get()
    if req is not None:
        # If already in a request connection, start a nested transaction
        async with req.begin_nested() as _:
            yield req
    else:
        engine = await get_engine()
        async with engine.begin() as conn:
            yield conn


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
        # Resolve the target model's PK type so FK column uses a matching SA type
        target_model = field.resolve_target()
        if target_model:
            target_fields = getattr(target_model, "_fields", {})
            for _fname, tfield in target_fields.items():
                if getattr(tfield, "primary_key", False):
                    if isinstance(tfield, UUIDField):
                        return sa.String(36)
                    if isinstance(tfield, CharField):
                        return sa.String(tfield.max_length)
                    if isinstance(tfield, BigIntegerField):
                        return sa.BigInteger()
                    break  # default to Integer for IntegerField / unknown
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
# Relationship Traversal & JOINs
# ---------------------------------------------------------------------------


def _build_traversal_joins(
    traversal: Any,  # TraversalLookup instance
    base_table: sa.Table,
) -> tuple[sa.FromClause, sa.Table]:
    """Build JOINs for relationship traversal and return joined clause and final table.

    Args:
        traversal: TraversalLookup instance containing FK steps
        base_table: SQLAlchemy table for the base model

    Returns:
        (from_clause, final_table) where from_clause contains all the JOINs
    """
    from_clause: sa.FromClause = base_table
    join_steps = traversal.get_joins_needed()

    if not join_steps:
        # No traversal, just return base
        return from_clause, base_table

    # Build JOINs for each FK step
    for _i, step in enumerate(join_steps):
        # Get the FK field's column on current table
        fk_column = step.field.column_name
        if fk_column not in from_clause.c:
            # Try without _id suffix if needed
            if f"{step.field.name}_id" in from_clause.c:
                fk_column = f"{step.field.name}_id"
            else:
                raise ValueError(f"Cannot find FK column '{fk_column}' on table")

        # Get the related model's table
        related_model = step.field.resolve_target()
        related_table = get_table(related_model)

        # Build JOIN condition: current_table.fk_id == related_table.id
        join_condition = from_clause.c[fk_column] == related_table.c.id

        # Create LEFT OUTER JOIN to support NULL foreign keys
        from_clause = from_clause.outerjoin(related_table, join_condition)

    # Get final table (last target in the traversal)
    return from_clause, get_table(traversal.final_model)


# ---------------------------------------------------------------------------
# Filter compiler
# ---------------------------------------------------------------------------


def _compile_traversal_filter(
    model_cls: type, key: str, value: Any, base_table: sa.Table
) -> tuple[sa.ColumnElement[Any] | None, list[sa.FromClause]]:
    """Compile a traversal filter (e.g., author__username="john") with JOINs.

    Args:
        model_cls: The base model class
        key: Filter key with __ traversal (e.g., "author__username__contains")
        value: Filter value
        base_table: SQLAlchemy table for the base model

    Returns:
        (where_clause, joins) tuple where joins is list of SQLAlchemy FROM clauses
    """

    try:
        lookup_obj = _cached_traversal_lookup(key, model_cls)
    except FieldError:
        # Invalid traversal, return None (filter ignored)
        return None, []

    if lookup_obj.is_simple_field():
        # Not a traversal, compile normally
        col_name = lookup_obj.final_field.column_name
        if col_name not in base_table.c and f"{col_name}_id" in base_table.c:
            col_name = f"{col_name}_id"
        col = base_table.c[col_name]
        where_clause = _apply_lookup(col, "", value)
        return where_clause, []

    # Build JOINs for traversal
    from_clause, final_table = _build_traversal_joins(lookup_obj, base_table)

    # Extract lookup operator from the final part
    # e.g., "author__username__contains" -> lookup="contains"
    parts = key.split("__")
    lookup = ""  # infer from final parts if available

    # The lookup is anything after all the FK traversals.
    # Join steps consume one segment each (fk field name), plus the final field name.
    # Any remaining segment is the lookup operator.
    traversal_depth = len(lookup_obj.get_joins_needed()) + 1  # fk steps + final field
    if len(parts) > traversal_depth:
        lookup = parts[traversal_depth]

    # Get final column
    final_field = lookup_obj.final_field
    col_name = final_field.name
    if hasattr(final_field, "column_name") and final_field.column_name != final_field.name:
        col_name = final_field.column_name

    col = final_table.c[col_name]
    where_clause = _apply_lookup(col, lookup, value)

    # Collect all JOINs from the from_clause
    # The from_clause is a join with multiple tables, we need to extract it
    joins = [from_clause] if from_clause != base_table else []

    return where_clause, joins


def _escape_like(value: Any) -> str:
    """Escape LIKE metacharacters (% and _) in user-provided values.

    Prevents LIKE injection attacks where malicious input like '%' could
    match all rows or '%%' could cause expensive pattern matching.
    """
    str_value: str = value if isinstance(value, str) else str(value)
    # Escape backslash first (it's the escape character), then % and _
    return str_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_lookup(col: sa.ColumnElement[Any], lookup: str, value: Any) -> sa.ColumnElement[Any]:
    """Apply a lookup operator to a column."""
    # Unwrap LazyFK values to raw IDs for SQL binding
    if isinstance(value, LazyFK):
        value = value.fk_id
    # Convert UUID objects to strings for database comparison
    if isinstance(value, uuid.UUID):
        value = str(value)

    if lookup in ("exact", ""):
        return col == value  # type: ignore[no-any-return]
    if lookup == "contains":
        escaped_value = _escape_like(value)
        return col.like(f"%{escaped_value}%", escape="\\")
    if lookup == "icontains":
        escaped_value = _escape_like(value)
        return col.ilike(f"%{escaped_value}%", escape="\\")
    if lookup == "startswith":
        escaped_value = _escape_like(value)
        return col.like(f"{escaped_value}%", escape="\\")
    if lookup == "endswith":
        escaped_value = _escape_like(value)
        return col.like(f"%{escaped_value}", escape="\\")
    if lookup == "gt":
        return col > value  # type: ignore[no-any-return]
    if lookup == "gte":
        return col >= value  # type: ignore[no-any-return]
    if lookup == "lt":
        return col < value  # type: ignore[no-any-return]
    if lookup == "lte":
        return col <= value  # type: ignore[no-any-return]
    if lookup == "in":
        value = [v.fk_id if isinstance(v, LazyFK) else v for v in value]
        return col.in_(value)
    if lookup == "isnull":
        return col.is_(None) if value else col.isnot(None)
    if lookup == "range":
        lo, hi = value
        return col.between(lo, hi)
    return col == value  # type: ignore[no-any-return]


def _compile_single_filter(
    table: sa.Table, key: str, value: Any, model_cls: type | None = None
) -> sa.ColumnElement[Any] | None:
    """Compile one ``field__lookup=value`` pair to a SQLAlchemy clause.

    This is the legacy interface that returns only the WHERE clause.
    For traversal support with JOINs, use execute_select directly.
    """
    parts = key.split("__", 1)
    col_name = parts[0]
    lookup = parts[1] if len(parts) > 1 else "exact"

    # Support FK _id column aliases (e.g. filter(author=5) -> author_id column)
    if col_name not in table.c and f"{col_name}_id" in table.c:
        col_name = f"{col_name}_id"

    if col_name not in table.c:
        return None

    col = table.c[col_name]
    return _apply_lookup(col, lookup, value)


def _compile_q(table: sa.Table, q_obj: Any) -> sa.ColumnElement[Any] | None:
    """Recursively compile a Q object to a SQLAlchemy clause.

    Duck-typed: ``q_obj`` must expose ``.children`` (list of ``(key, value)``
    tuples or nested Q-like objects), ``.connector`` ("AND"/"OR"), and
    ``.negated`` (bool).  This matches :class:`~openviper.db.models.Q` exactly
    without creating a circular import.
    """
    if not q_obj.children:
        return None

    clauses: list[sa.ColumnElement[Any]] = []
    for child in q_obj.children:
        if isinstance(child, tuple):
            key, value = child
            clause = _compile_single_filter(table, key, value)
        else:
            clause = _compile_q(table, child)
        if clause is not None:
            clauses.append(clause)

    if not clauses:
        return None

    combined: sa.ColumnElement[Any] = (
        sa.or_(*clauses) if getattr(q_obj, "connector", "AND") == "OR" else sa.and_(*clauses)
    )
    return sa.not_(combined) if getattr(q_obj, "negated", False) else combined


def _compile_filters(
    table: sa.Table, filter_dicts: list[dict[str, Any]]
) -> sa.ColumnElement[Any] | None:
    """Convert ORM filter dicts to an ANDed SQLAlchemy clause."""
    clauses: list[sa.ColumnElement[Any]] = []
    for filters in filter_dicts:
        for key, value in filters.items():
            clause = _compile_single_filter(table, key, value)
            if clause is not None:
                clauses.append(clause)
    return sa.and_(*clauses) if clauses else None


def _compile_excludes(
    table: sa.Table, exclude_dicts: list[dict[str, Any]]
) -> sa.ColumnElement[Any] | None:
    filters_clause = _compile_filters(table, exclude_dicts)
    if filters_clause is None:
        return None
    return sa.not_(filters_clause)


def _build_where_clause(
    table: sa.Table,
    filter_dicts: list[dict[str, Any]],
    exclude_dicts: list[dict[str, Any]],
    q_filters: list[Any],
) -> sa.ColumnElement[Any] | None:
    """Combine filter dicts, exclude dicts, and Q objects into one WHERE clause."""
    parts: list[sa.ColumnElement[Any]] = []
    f = _compile_filters(table, filter_dicts)
    if f is not None:
        parts.append(f)
    e = _compile_excludes(table, exclude_dicts)
    if e is not None:
        parts.append(e)
    for q_obj in q_filters:
        q_clause = _compile_q(table, q_obj)
        if q_clause is not None:
            parts.append(q_clause)
    return sa.and_(*parts) if parts else None


def _build_where_clause_with_traversals(
    model_cls: type,
    base_table: sa.Table,
    filter_dicts: list[dict[str, Any]],
    exclude_dicts: list[dict[str, Any]],
    q_filters: list[Any],
    initial_from_clause: Any = None,
) -> tuple[sa.ColumnElement[Any] | None, sa.FromClause]:
    """Build WHERE clause while collecting traversal JOINs.

    Args:
        initial_from_clause: Optional pre-built from clause (e.g. from
            select_related JOINs).  Traversal JOINs are chained on top so
            that both sets of JOINs are preserved in a single FROM clause.

    Returns:
        (where_clause, from_clause_with_joins) tuple
    """

    parts: list[sa.ColumnElement[Any]] = []
    from_clause = initial_from_clause if initial_from_clause is not None else base_table
    # Maps join key → (from_clause, final_table) to avoid rebuilding duplicate JOINs
    collected_joins: dict[str, tuple[sa.FromClause, sa.Table]] = {}

    # Process filters with traversal support
    for filters in filter_dicts:
        for key, value in filters.items():
            # Try traversal parsing
            try:
                traversal = _cached_traversal_lookup(key, model_cls)
                if not traversal.is_simple_field():
                    # Check join cache before building to avoid redundant work
                    if key in collected_joins:
                        traversal_from, final_table = collected_joins[key]
                    else:
                        traversal_from, final_table = _build_traversal_joins(traversal, base_table)
                        collected_joins[key] = (traversal_from, final_table)
                        from_clause = traversal_from

                    # Compile filter on final table
                    col = final_table.c[traversal.final_field.column_name]
                    clause = _apply_lookup(col, "", value)
                    if clause is not None:
                        parts.append(clause)
                    continue
            except FieldError:
                pass

            # Normal field compilation fallback
            fallback_clause = _compile_single_filter(base_table, key, value)
            if fallback_clause is not None:
                parts.append(fallback_clause)

    # Process excludes (can also use traversals)
    for excludes in exclude_dicts:
        for key, value in excludes.items():
            try:
                traversal = _cached_traversal_lookup(key, model_cls)
                if not traversal.is_simple_field():
                    if key in collected_joins:
                        traversal_from, final_table = collected_joins[key]
                    else:
                        traversal_from, final_table = _build_traversal_joins(traversal, base_table)
                        collected_joins[key] = (traversal_from, final_table)
                        from_clause = traversal_from

                    col = final_table.c[traversal.final_field.column_name]
                    clause = _apply_lookup(col, "", value)
                    if clause is not None:
                        parts.append(sa.not_(clause))
                    continue
            except FieldError:
                pass

            # Normal exclude fallback
            fallback_exclude = _compile_single_filter(base_table, key, value)
            if fallback_exclude is not None:
                parts.append(sa.not_(fallback_exclude))

    # Q objects compile against base_table (TODO: could support traversal too)
    for q_obj in q_filters:
        q_clause = _compile_q(base_table, q_obj)
        if q_clause is not None:
            parts.append(q_clause)

    where_clause = sa.and_(*parts) if parts else None
    return where_clause, from_clause


def _is_f_like(v: Any) -> bool:
    """Return True if *v* is an F or _FExpr (duck-typed, no import)."""
    return (
        hasattr(v, "name")
        and not hasattr(v, "lhs")
        and not hasattr(v, "func")
        or (hasattr(v, "lhs") and hasattr(v, "op") and hasattr(v, "rhs"))
    )


def _f_expr_as_sa(table: sa.Table, expr: Any) -> Any:
    """Convert an F reference or _FExpr arithmetic tree to a SQLAlchemy expression.

    Duck-typed: works without importing F / _FExpr from models to avoid circulars.
    Returns ``None`` when the field cannot be resolved.
    """
    # _FExpr (has lhs/op/rhs)
    if hasattr(expr, "lhs") and hasattr(expr, "op") and hasattr(expr, "rhs"):
        lhs = _f_expr_as_sa(table, expr.lhs) if _is_f_like(expr.lhs) else expr.lhs
        rhs = _f_expr_as_sa(table, expr.rhs) if _is_f_like(expr.rhs) else expr.rhs
        if lhs is None or rhs is None:
            return None
        if expr.op == "+":
            return lhs + rhs
        if expr.op == "-":
            return lhs - rhs
        if expr.op == "*":
            return lhs * rhs
        if expr.op == "/":
            return lhs / rhs
        return None

    # F reference (has name, no lhs, no func)
    if hasattr(expr, "name") and not hasattr(expr, "lhs") and not hasattr(expr, "func"):
        col_name: str = expr.name
        if col_name in table.c:
            return table.c[col_name]
        if f"{col_name}_id" in table.c:
            return table.c[f"{col_name}_id"]
        return None

    return None


def _ann_expr_as_sa(table: sa.Table, expr: Any) -> Any:
    """Convert an annotation expression (F, _FExpr, _Aggregate) to SQLAlchemy.

    Returns ``None`` for unsupported types.
    """
    # _Aggregate subclass (has func + field)
    if hasattr(expr, "func") and hasattr(expr, "field"):
        col_name: str = expr.field
        if col_name not in table.c:
            if f"{col_name}_id" in table.c:
                col_name = f"{col_name}_id"
            else:
                return None
        col: Any = table.c[col_name]
        if getattr(expr, "distinct", False):
            col = col.distinct()
        sa_func = getattr(sa.func, expr.func.lower(), None)
        if sa_func is None:
            return None
        return sa_func(col)

    # F or _FExpr
    if _is_f_like(expr):
        return _f_expr_as_sa(table, expr)

    return None


# ---------------------------------------------------------------------------
# Execute helpers
# ---------------------------------------------------------------------------


async def execute_select(qs: QuerySet) -> list[dict[str, Any]]:
    model_cls = qs._model
    table = get_table(model_cls)

    # ── select_related JOINs ──────────────────────────────────────────────
    from_clause: Any = table
    extra_cols: list[Any] = []

    for field_name in qs._select_related:
        if field_name not in model_cls._fields:
            continue
        field = model_cls._fields[field_name]
        if not isinstance(field, (ForeignKey, OneToOneField)):
            continue
        related_cls = field.resolve_target()
        if related_cls is None:
            continue
        related_table = get_table(related_cls)
        from_clause = from_clause.join(
            related_table,
            table.c[field.column_name] == related_table.c.id,
            isouter=False,
        )
        extra_cols.extend(col.label(f"{field_name}__{col.name}") for col in related_table.c)

    # ── WHERE + traversal JOINs (chains off any select_related joins) ─────
    # Build WHERE and final from_clause together so traversal JOINs are
    # stacked on top of select_related JOINs in a single pass, avoiding
    # the need to rebuild the statement after the fact.
    q_filters = getattr(qs, "_q_filters", [])
    where, from_clause = _build_where_clause_with_traversals(
        model_cls,
        table,
        qs._filters,
        qs._excludes,
        q_filters,
        initial_from_clause=from_clause,
    )

    # ── Column selection (only / defer) ───────────────────────────────────
    only_fields: list[str] = getattr(qs, "_only_fields", [])
    defer_fields: list[str] = getattr(qs, "_defer_fields", [])

    if only_fields:
        wanted: set[str] = set(only_fields) | {"id"}
        base_cols: list[Any] = [col for col in table.c if col.name in wanted]
    elif defer_fields:
        deferred: set[str] = {
            (model_cls._fields[f].column_name if f in model_cls._fields else f)
            for f in defer_fields
        }
        base_cols = [col for col in table.c if col.name not in deferred]
    else:
        base_cols = list(table.c)

    # ── Build SELECT statement once with the final from_clause ────────────
    # Avoids rebuilding sa.select() multiple times as JOINs are discovered.
    all_sel = [*base_cols, *extra_cols]
    stmt = (
        sa.select(*all_sel).select_from(from_clause)
        if from_clause is not table
        else sa.select(*all_sel)
    )

    # ── Annotations ───────────────────────────────────────────────────────
    annotations: dict[str, Any] = getattr(qs, "_annotations", {})
    if annotations:
        ann_cols = [
            sa_expr.label(alias)
            for alias, expr in annotations.items()
            if (sa_expr := _ann_expr_as_sa(table, expr)) is not None
        ]
        if ann_cols:
            stmt = stmt.add_columns(*ann_cols)

    # ── WHERE ─────────────────────────────────────────────────────────────
    if where is not None:
        stmt = stmt.where(where)

    # ── ORDER BY ─────────────────────────────────────────────────────────
    for field_name in qs._order:
        desc = field_name.startswith("-")
        col_name = field_name.lstrip("-")
        if col_name in table.c:
            col = table.c[col_name]
            stmt = stmt.order_by(col.desc() if desc else col.asc())

    # ── DISTINCT ─────────────────────────────────────────────────────────
    if getattr(qs, "_distinct", False):
        stmt = stmt.distinct()

    # ── LIMIT / OFFSET ───────────────────────────────────────────────────
    stmt = stmt.limit(qs._limit if qs._limit is not None else MAX_QUERY_ROWS)
    if qs._offset is not None:
        stmt = stmt.offset(qs._offset)

    async with _connect() as conn:
        try:
            result = await conn.execute(stmt)
            return [dict(row) for row in result.mappings()]
        except Exception as e:
            logger.error(
                "SELECT query failed for model %s: %s",
                model_cls.__name__,
                str(e),
                exc_info=True,
                extra={
                    "model": model_cls.__name__,
                    "filters": qs._filters,
                    "excludes": qs._excludes,
                },
            )
            raise


async def execute_count(qs: QuerySet) -> int:
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(sa.func.count()).select_from(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    async with _connect() as conn:
        result = await conn.execute(stmt)
        return int(result.scalar_one())


async def execute_exists(qs: QuerySet) -> bool:
    """Check existence with SELECT 1 ... LIMIT 1 — stops at the first match."""
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(sa.literal(1)).select_from(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    stmt = stmt.limit(1)

    async with _connect() as conn:
        result = await conn.execute(stmt)
        return result.first() is not None


async def execute_delete(qs: QuerySet) -> int:
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.delete(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    try:
        async with _begin() as conn:
            result = await conn.execute(stmt)
            return int(result.rowcount)
    except Exception as e:
        logger.error(
            "Bulk DELETE failed for model %s: %s",
            model_cls.__name__,
            str(e),
            exc_info=True,
            extra={"model": model_cls.__name__, "filters": qs._filters, "excludes": qs._excludes},
        )
        raise


async def execute_update(qs: QuerySet, values: dict[str, Any]) -> int:
    skip = qs._ignore_permissions or _bypass_permissions.get()
    await check_permission_for_model(qs._model, "update", ignore_permissions=skip)

    model_cls = qs._model
    table = get_table(model_cls)

    field_defs = model_cls._fields
    db_values: dict[str, Any] = {}
    for k, v in values.items():
        field_def = field_defs.get(k)
        if _is_f_like(v):
            # F / _FExpr — resolve column reference(s) directly
            col_name = field_def.column_name if field_def else k
            sa_expr = _f_expr_as_sa(table, v)
            if sa_expr is not None:
                db_values[col_name] = sa_expr
        elif field_def is not None:
            db_values[field_def.column_name] = field_def.to_db(v)
        else:
            db_values[k] = v

    stmt = sa.update(table).values(**db_values)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    try:
        async with _begin() as conn:
            result = await conn.execute(stmt)
            return int(result.rowcount)
    except Exception as e:
        logger.error(
            "Bulk UPDATE failed for model %s: %s",
            model_cls.__name__,
            str(e),
            exc_info=True,
            extra={"model": model_cls.__name__, "filters": qs._filters, "values": values},
        )
        raise


async def execute_save(instance: Model, ignore_permissions: bool = False) -> None:
    """INSERT or UPDATE a single model instance."""
    model_cls = type(instance)
    action = "update" if getattr(instance, "pk", None) else "create"
    # Honour both the ContextVar (preferred) and the legacy flag
    skip = ignore_permissions or _bypass_permissions.get()
    await check_permission_for_model(model_cls, action, ignore_permissions=skip)

    table = get_table(model_cls)
    instance._apply_auto_fields()

    # Load soft-removed columns so we can skip them during save.
    await _load_soft_removed_columns()
    soft_removed = get_soft_removed_columns(model_cls._table_name)

    # Fast path: if no soft-removed columns, avoid membership checks in loop
    has_soft_removed = bool(soft_removed)

    data = {}
    for name, field in model_cls._fields.items():
        val = getattr(instance, name)
        await field.pre_save(instance, val)
        # Re-fetch value in case pre_save modified it (e.g. UploadFile -> str path)
        val = getattr(instance, name)

        if field.primary_key and field.auto_increment and val is None:
            continue
        if has_soft_removed and field.column_name in soft_removed:
            continue
        data[field.column_name] = field.to_db(val)

    pk_val = getattr(instance, "id", None)
    is_new = pk_val is None

    if not is_new and hasattr(instance, "_previous_state") and instance._previous_state:
        # Check if this is a user-created instance vs DB-loaded instance.
        # DB-loaded instances have ID in _previous_state matching current ID.
        # User-created instances with auto-UUID have None in _previous_state but current ID set.
        prev_id = instance._previous_state.get("id")
        if prev_id is None:
            # ID in _previous_state was None - this is a user-created instance
            is_new = True
        elif prev_id != pk_val:
            # ID changed - treat as new (unusual case, client-side assigned)
            is_new = True
        # else: prev_id == pk_val, so it came from DB, keep is_new = False

    if is_new:
        stmt = sa.insert(table).values(**data)
        try:
            async with _begin() as conn:
                result = await conn.execute(stmt)
                # Only update instance.id if it's not already set (for auto-increment)
                if pk_val is None:
                    instance.id = cast("Any", result).inserted_primary_key[0]
        except Exception as e:
            logger.error(
                "INSERT failed for model %s: %s",
                model_cls.__name__,
                str(e),
                exc_info=True,
            )
            raise
    else:
        upd_stmt = sa.update(table).where(table.c.id == pk_val).values(**data)
        try:
            async with _begin() as conn:
                result = await conn.execute(upd_stmt)
                if result.rowcount == 0:
                    # No row matched the UPDATE — the PK was user-assigned on a new instance.
                    # Fall back to INSERT.
                    logger.warning(
                        "UPDATE matched 0 rows for %s (pk=%s), falling back to INSERT",
                        model_cls.__name__,
                        pk_val,
                    )
                    ins_stmt = sa.insert(table).values(**data)
                    await conn.execute(ins_stmt)
        except Exception as e:
            logger.error(
                "UPDATE failed for model %s (pk=%s): %s",
                model_cls.__name__,
                pk_val,
                str(e),
                exc_info=True,
            )
            raise


async def execute_delete_instance(instance: Model, ignore_permissions: bool = False) -> None:
    """Delete a single model instance by primary key."""
    model_cls = type(instance)
    # Honour both the ContextVar (preferred) and the legacy flag
    skip = ignore_permissions or _bypass_permissions.get()
    await check_permission_for_model(model_cls, "delete", ignore_permissions=skip)

    table = get_table(model_cls)
    pk_val = instance.id

    try:
        async with _begin() as conn:
            await conn.execute(sa.delete(table).where(table.c.id == pk_val))
    except Exception as e:
        logger.error(
            "DELETE failed for model %s (pk=%s): %s",
            model_cls.__name__,
            pk_val,
            str(e),
            exc_info=True,
            extra={"model": model_cls.__name__, "operation": "DELETE", "pk": pk_val},
        )
        raise


async def execute_values(
    qs: QuerySet, fields: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Execute a SELECT and return raw dicts, optionally restricted to *fields*.

    Annotations from ``qs._annotations`` are included as extra columns.
    """
    model_cls = qs._model
    table = get_table(model_cls)

    annotations: dict[str, Any] = getattr(qs, "_annotations", {})

    if fields:
        # Resolve field names → column names
        field_defs = model_cls._fields
        wanted_cols: list[Any] = []
        for fname in fields:
            if fname in annotations:
                sa_expr = _ann_expr_as_sa(table, annotations[fname])
                if sa_expr is not None:
                    wanted_cols.append(sa_expr.label(fname))
            else:
                field_def = field_defs.get(fname)
                col_name = field_def.column_name if field_def else fname
                if col_name in table.c:
                    wanted_cols.append(table.c[col_name].label(fname))
        stmt = sa.select(*wanted_cols) if wanted_cols else sa.select(table)
    else:
        ann_cols = [
            sa_expr.label(alias)
            for alias, expr in annotations.items()
            if (sa_expr := _ann_expr_as_sa(table, expr)) is not None
        ]
        stmt = sa.select(*table.c, *ann_cols) if ann_cols else sa.select(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    for field_name in qs._order:
        desc = field_name.startswith("-")
        col_name = field_name.lstrip("-")
        if col_name in table.c:
            col = table.c[col_name]
            stmt = stmt.order_by(col.desc() if desc else col.asc())

    if getattr(qs, "_distinct", False):
        stmt = stmt.distinct()
    stmt = stmt.limit(qs._limit if qs._limit is not None else MAX_QUERY_ROWS)
    if qs._offset is not None:
        stmt = stmt.offset(qs._offset)

    async with _connect() as conn:
        result = await conn.execute(stmt)
        return [dict(row) for row in result.mappings()]


async def execute_aggregate(qs: QuerySet, agg_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute aggregate functions and return a single-row result dict.

    *agg_kwargs* maps alias names to _Aggregate instances.
    """
    model_cls = qs._model
    table = get_table(model_cls)

    agg_cols: list[Any] = []
    for alias, expr in agg_kwargs.items():
        sa_expr = _ann_expr_as_sa(table, expr)
        if sa_expr is not None:
            agg_cols.append(sa_expr.label(alias))

    if not agg_cols:
        return {}

    stmt = sa.select(*agg_cols)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    async with _connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else {}


async def execute_explain(qs: QuerySet) -> str:
    """Return the database EXPLAIN output for the current query as a string."""
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

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
    dialect_name: str = engine.dialect.name

    async with _connect() as conn:
        if dialect_name == "postgresql":
            from sqlalchemy.dialects import postgresql

            compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
            explain_text = f"EXPLAIN {compiled}"
            result = await conn.execute(sa.text(explain_text))
            lines = [str(row[0]) for row in result]
        elif dialect_name == "sqlite":
            # Do not use literal_binds=True with sa.text() — baking user-controlled
            # filter values into the SQL string via literal_binds and then executing
            # it bypasses parameterized queries, creating a SQL injection vector.
            # Return the compiled query plan string without executing it.
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            lines = [f"EXPLAIN QUERY PLAN {compiled}"]
        else:
            # Generic fallback — compile to string only
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            lines = [f"EXPLAIN {compiled}"]

    return "\n".join(lines)


async def execute_bulk_update(
    model_cls: type,
    objs: list[Any],
    fields: list[str],
    batch_size: int | None = None,
) -> int:
    """Batch-UPDATE *fields* on a list of model instances.

    Uses a single parameterised UPDATE with ``executemany`` semantics so the
    database driver can pipeline the statements.  Falls back to per-row
    updates when the driver does not support batching.

    Returns the total number of rows updated.  If *batch_size* is given each
    batch is committed separately to keep transaction size bounded.
    """
    if not objs or not fields:
        return 0

    table = get_table(model_cls)
    field_defs = cast("Any", model_cls)._fields

    # Resolve field → column name mapping once.
    col_map: dict[str, str] = {}
    for fname in fields:
        if fname in field_defs:
            col_map[fname] = field_defs[fname].column_name
        else:
            col_map[fname] = fname

    # Build parameter dicts (one per object).
    param_rows: list[dict[str, Any]] = []
    for obj in objs:
        pk_val = getattr(obj, "id", None) or getattr(obj, "pk", None)
        if pk_val is None:
            continue
        params: dict[str, Any] = {"_pk": pk_val}
        for fname in fields:
            raw_val = getattr(obj, fname, None)
            if fname in field_defs:
                params[col_map[fname]] = field_defs[fname].to_db(raw_val)
            else:
                params[col_map[fname]] = raw_val
        param_rows.append(params)

    if not param_rows:
        return 0

    # Build a single parameterised UPDATE statement.
    set_clause: dict[str, Any] = {col_map[f]: sa.bindparam(col_map[f]) for f in fields}
    upd_stmt = sa.update(table).where(table.c.id == sa.bindparam("_pk")).values(**set_clause)

    total = 0
    size = batch_size if (batch_size and batch_size > 0) else len(param_rows)
    for i in range(0, len(param_rows), size):
        batch = param_rows[i : i + size]
        async with _begin() as conn:
            result = await conn.execute(upd_stmt, batch)
            total += result.rowcount

    return total


async def execute_select_stream(
    qs: QuerySet, chunk_size: int = 1000
) -> AsyncGenerator[dict[str, Any]]:
    """Yield rows one at a time using a server-side cursor.

    Uses ``conn.stream()`` + ``yield_per()`` to avoid loading the entire
    result set into memory.  Ideal for large-table iteration.
    """
    await check_permission_for_model(
        qs._model, "read", ignore_permissions=qs._ignore_permissions or _bypass_permissions.get()
    )

    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = _build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

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

    async with _connect() as conn:
        result = await conn.stream(stmt)
        async for row in result.mappings().yield_per(chunk_size):
            yield dict(row)
