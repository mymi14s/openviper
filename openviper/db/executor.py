"""Low-level SQL execution helpers used by the ORM layer."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import logging
import re
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as _pg_dialect
from sqlalchemy.exc import (
    DBAPIError as SADBAPIError,
)
from sqlalchemy.exc import (
    OperationalError as SAOperationalError,
)
from sqlalchemy.exc import (
    ProgrammingError as SAProgrammingError,
)
from sqlalchemy.sql.sqltypes import Uuid

from openviper.auth.permission_core import check_permission_for_model
from openviper.conf import settings
from openviper.db import _model_registry
from openviper.db._traversal import TraversalLookup
from openviper.db.connection import (
    _request_conn,
    _transaction_alias,
    _transaction_writes_allowed,
    get_engine,
    get_metadata,
)
from openviper.db.connections import DEFAULT_ALIAS, connections
from openviper.db.exceptions import (
    DatabaseAliasNotFoundError,
    DatabaseReadOnlyError,
    DatabaseTransactionRoutingError,
)
from openviper.db.fields import (
    AutoField,
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
    ManyToManyField,
    OneToOneField,
    TimeField,
    UUIDField,
)
from openviper.db.migrations.executor import get_soft_removed_table
from openviper.db.routing.resolver import resolver
from openviper.db.utils import get_per_loop_lock
from openviper.exceptions import FieldError, TableNotFound

_SAFE_TABLE_NAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Maximum length for regex lookup patterns to prevent ReDoS attacks.
_MAX_REGEX_LENGTH: int = 500

# Nested quantifiers like (a+)+, (a*)*, (a+)* etc. are the primary vector.
_REDoS_PATTERN: re.Pattern[str] = re.compile(
    r"""
    \([^)]*[+*][^)]*\)\s*[+*]       # Nested quantifiers: (a+)+, (a*)*, etc.
    | \([^)]*\|[^)]*\)\s*[+*]       # Alternation with quantifier: (a|b)+
    | \(\?\:?\([^)]*[+*]            # Non-capturing nested: (?:(a+))
    | \(\?P?<[a-zA-Z]+>[^)]*[+*]    # Named group with quantifier: (?P<name>a+)
    """,
    re.VERBOSE,
)


def validate_regex_pattern(pattern: str) -> None:
    """Reject regex patterns that could cause catastrophic backtracking (ReDoS).

    Enforces a maximum length and blocks known-dangerous nested quantifier
    patterns.  This is a best-effort heuristic - callers should also set
    query timeouts as defense-in-depth.
    """
    if not isinstance(pattern, str):
        raise FieldError(f"Regex lookup requires a string pattern, got {type(pattern).__name__}.")
    if len(pattern) > _MAX_REGEX_LENGTH:
        raise FieldError(f"Regex pattern exceeds maximum length of {_MAX_REGEX_LENGTH} characters.")
    if _REDoS_PATTERN.search(pattern):
        raise FieldError(
            f"Regex pattern contains potentially catastrophic nested quantifiers: {pattern!r}"
        )


def assert_safe_table_name(name: str) -> None:
    """Raise ValueError if the table name contains unsafe characters."""
    if not _SAFE_TABLE_NAME_RE.match(name):
        raise ValueError(f"Unsafe table name: {name!r}")


# Field names that commonly hold sensitive data and should be redacted in logs.
_SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "secret",
        "token",
        "api_key",
        "api_secret",
        "access_token",
        "refresh_token",
        "private_key",
        "credit_card",
        "ssn",
    }
)


def redact_filters(
    filters: list[dict[str, object]] | dict[str, object],
) -> list[dict[str, str]]:
    """Redact sensitive field values from filter dicts for safe logging.

    Replaces values whose keys match known sensitive field names with
    ``"[REDACTED]"`` to prevent credential and PII leakage in log output.
    """
    if isinstance(filters, dict):
        filters = [filters]
    redacted: list[dict[str, str]] = []
    for f in filters:
        entry: dict[str, str] = {}
        for key, value in f.items():
            # Extract the base field name (before __lookup suffix).
            base = key.split("__")[0]
            entry[key] = "[REDACTED]" if base in _SENSITIVE_FIELD_NAMES else repr(value)
        redacted.append(entry)
    return redacted


def redact_values(values: dict[str, object]) -> dict[str, str]:
    """Redact sensitive field values from update dicts for safe logging."""
    result: dict[str, str] = {}
    for key, value in values.items():
        result[key] = "[REDACTED]" if key in _SENSITIVE_FIELD_NAMES else repr(value)
    return result


# Patterns reported by different DB backends when a table is missing.
_TABLE_MISSING_RE: re.Pattern[str] = re.compile(
    r"no such table|doesn't exist|does not exist|undefined table",
    re.IGNORECASE,
)


def check_table_missing(exc: Exception, model_cls: type) -> None:
    """Re-raise *exc* as :class:`TableNotFound` when the DB reports a missing table.

    Clears the full SQLAlchemy traceback so only a clean 503 propagates.
    """
    if isinstance(exc, (SAOperationalError, SAProgrammingError)) and _TABLE_MISSING_RE.search(
        str(exc)
    ):
        table_name: str = getattr(model_cls, "_table_name", model_cls.__name__)
        raise TableNotFound(model_cls.__name__, table_name) from None


def is_data_error(exc: SADBAPIError) -> bool:
    """Return True when *exc* represents invalid query parameter data.

    Drivers raise this for values that cannot be cast to the target column
    type (e.g. an empty string supplied for a UUID column).  Such queries
    can never match any row, so callers may safely treat the result as empty.
    """
    orig = getattr(exc, "orig", None)
    if orig is not None:
        orig_type = type(orig).__name__
        if "DataError" in orig_type or "InvalidTextRepresentation" in orig_type:
            return True
    return "DataError" in type(exc).__name__ or "invalid input" in str(exc).lower()


# Patterns reported by different DB backends when a column/field is missing.
_FIELD_MISSING_RE: re.Pattern[str] = re.compile(
    r"column[^\n]*does not exist|no such column|undefined column",
    re.IGNORECASE,
)

# Pattern to extract the field/column name from database error messages.
_FIELD_NAME_EXTRACT_RE: re.Pattern[str] = re.compile(
    r"""
    (?:column\s+["']?([^"'\s().]+)["']?\s+does\s+not\s+exist)|  # PostgreSQL
    (?:no\s+such\s+column:\s+(?:\w+\.)?([^\s]+))|              # SQLite
    (?:Unknown\s+column\s+['"]([^'"]+)['"])|                   # MySQL
    (?:["']([^"'\s().]+)["']\s+does\s+not\s+exist)             # Alternative PostgreSQL
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_field_names(error_msg: str) -> list[str]:
    """Extract unknown field names from a database error message."""
    fields = []
    for match in _FIELD_NAME_EXTRACT_RE.finditer(error_msg):
        field = next((g for g in match.groups() if g), None)
        if field:
            # Strip table prefix if present (e.g., "table.column" -> "column")
            field = field.split(".")[-1]
            if field not in fields:
                fields.append(field)
    return fields


def check_field_missing(exc: Exception, model_cls: type) -> None:
    """Raise :class:`FieldError` when the DB reports a missing column.

    Converts low-level database "column does not exist" errors into a clean
    400 response so callers receive a descriptive message rather than a 500.
    """
    if isinstance(exc, SADBAPIError) and _FIELD_MISSING_RE.search(str(exc)):
        available = ", ".join(sorted(model_cls._fields))
        error_msg = str(exc)
        unknown_fields = extract_field_names(error_msg)

        # Log the raw database error for debugging
        logger.debug("Database error for %s: %s", model_cls.__name__, error_msg)

        if unknown_fields:
            fields_str = ", ".join(unknown_fields)
            raise FieldError(
                f"Query referenced a field that does not exist on {model_cls.__name__}. "
                f"Non Existent Fields: {fields_str}. "
                f"Available fields: {available}"
            ) from None
        else:
            raise FieldError(
                f"Query referenced a field that does not exist on {model_cls.__name__}. "
                f"Available fields: {available}"
            ) from None


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from openviper.db.models import Model, QuerySet

# Optional row cap applied to execute_select / execute_values when no
# explicit .limit() is set on the QuerySet.
# Set MAX_QUERY_ROWS in your project settings to enable a default cap.
# When unset (the default) no automatic limit is applied.


def max_query_rows() -> int | None:
    return getattr(settings, "MAX_QUERY_ROWS", None)


def query_cache_max_size() -> int:
    return int(getattr(settings, "QUERY_CACHE_MAX_SIZE", 2048))


class _QueryCache:
    """Bounded LRU cache with per-entry TTL and size limits for query results.

    Keys are ``(model_table_name, compiled_sql_hash)`` tuples.
    Values are ``(expire_time, rows)`` tuples.

    Per-entry size is bounded by ``_max_entry_rows`` to prevent a single
    massive result set from exhausting memory.

    A secondary index maps table names to their cache keys for O(1)
    model-level invalidation instead of scanning all entries.
    """

    __slots__ = ("_store", "_max_size", "_max_entry_rows", "_table_index")

    _DEFAULT_MAX_ENTRY_ROWS: int = 10_000

    def __init__(self, max_size: int, max_entry_rows: int | None = None) -> None:
        self._store: OrderedDict[str, tuple[float, list[dict[str, object]]]] = OrderedDict()
        self._max_size = max_size
        self._max_entry_rows = max_entry_rows or self._DEFAULT_MAX_ENTRY_ROWS
        self._table_index: dict[str, set[str]] = {}

    def get(self, key: str) -> list[dict[str, object]] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expire, rows = entry
        if time.monotonic() > expire:
            self._remove_key(key)
            return None
        self._store.move_to_end(key)
        return rows

    def put(self, key: str, rows: list[dict[str, object]], ttl: float) -> None:
        if ttl <= 0:
            return
        if len(rows) > self._max_entry_rows:
            logger.debug(
                "Query cache entry for key %s exceeds max_entry_rows=%d (got %d rows); not cached.",
                key,
                self._max_entry_rows,
                len(rows),
            )
            return
        self._store[key] = (time.monotonic() + ttl, rows)
        self._store.move_to_end(key)
        table_name = key.split(":", 1)[0]
        self._table_index.setdefault(table_name, set()).add(key)
        while len(self._store) > self._max_size:
            self._pop_oldest()

    def _remove_key(self, key: str) -> None:
        """Remove a key from the store and secondary index."""
        self._store.pop(key, None)
        table_name = key.split(":", 1)[0]
        bucket = self._table_index.get(table_name)
        if bucket is not None:
            bucket.discard(key)
            if not bucket:
                del self._table_index[table_name]

    def _pop_oldest(self) -> None:
        """Evict the oldest entry from the store and secondary index."""
        key, _ = self._store.popitem(last=False)
        table_name = key.split(":", 1)[0]
        bucket = self._table_index.get(table_name)
        if bucket is not None:
            bucket.discard(key)
            if not bucket:
                del self._table_index[table_name]

    def invalidate_model(self, table_name: str) -> None:
        """Remove all cached entries for a given table."""
        keys = self._table_index.pop(table_name, None)
        if keys is None:
            return
        for key in keys:
            self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._table_index.clear()

    def __len__(self) -> int:
        return len(self._store)


_query_cache: _QueryCache | None = None


def get_query_cache() -> _QueryCache:
    global _query_cache
    if _query_cache is None:
        _query_cache = _QueryCache(
            query_cache_max_size(),
            max_entry_rows=int(getattr(settings, "QUERY_CACHE_MAX_ENTRY_ROWS", 10_000)),
        )
    return _query_cache


def invalidate_query_cache(table_name: str | None = None) -> None:
    """Invalidate query cache entries and schema introspection cache.

    When a model is modified (e.g. after a migration or bulk operation),
    cached query results become stale and must be purged. The schema
    introspection cache (_REAL_COLUMNS_CACHE) is also cleared to ensure
    subsequent queries see the updated table structure.

    Args:
        table_name: If given, only entries for this table are removed.
                    If None, the entire cache is cleared.
    """
    cache = get_query_cache()
    if table_name:
        cache.invalidate_model(table_name)
    else:
        cache.clear()

    # Clear schema introspection cache to ensure migrations are reflected
    # immediately without requiring a process restart.
    if table_name:
        _REAL_COLUMNS_CACHE.pop(table_name, None)
    else:
        _REAL_COLUMNS_CACHE.clear()


def cache_key_for_stmt(table_name: str, stmt: Any) -> str:
    """Build a cache key from the compiled SQL string.

    Uses a deterministic hash (sha256) instead of Python's built-in hash()
    to ensure cache keys are consistent across process restarts and worker
    processes where PYTHONHASHSEED may differ.
    """
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    raw = f"{str(compiled)}|{compiled.params}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"{table_name}:{digest}"


# ContextVar that, when True, bypasses permission checks for the current task.
# Use bypass_permissions() context manager to set this for a scoped block.
# This is safer than passing ignore_permissions=True everywhere because it's
# explicitly scoped and cannot be accidentally left enabled.
_bypass_permissions: ContextVar[bool] = ContextVar("_bypass_permissions", default=False)


@contextlib.contextmanager
def bypass_permissions(*, reason: str | None = None) -> Generator[None]:
    """Context manager for temporarily bypassing permission checks.

    USE WITH EXTREME CAUTION. Only for trusted internal system operations
    such as migrations, auth backends, or fixture loading. Never expose this
    to user-controlled code paths.

    Every invocation is logged at WARNING level for audit traceability.

    Args:
        reason: Optional human-readable explanation for why permissions are
            being bypassed. This is included in the audit log to help with
            security reviews and debugging.

    Example::

        with bypass_permissions(reason="bulk import script"):
            await user.save()          # Permission check skipped
            await sensitive.delete()   # Permission check skipped
        # Permissions enforced again here
    """
    token = _bypass_permissions.set(True)
    reason_str = f" Reason: {reason}" if reason else ""
    logger.warning(
        "bypass_permissions() activated - all permission checks disabled.%s Caller: %s",
        reason_str,
        "".join(traceback.format_stack(limit=3)[:2]).strip(),
    )
    try:
        yield
    finally:
        _bypass_permissions.reset(token)


# Alias the shared cache dict for local use in executor functions.
# The dict object is shared with _model_registry so clearing one clears both.
SOFT_REMOVED_CACHE = _model_registry.soft_removed_cache
_soft_removed_lock: asyncio.Lock | None = None

# Cache for actual column names in the database to handle legacy/mismatched schemas
_REAL_COLUMNS_CACHE: dict[str, frozenset[str]] = {}

# Per-event-loop lock caches to prevent "bound to a different event loop" errors
_real_columns_lock_per_loop: dict[int, asyncio.Lock] = {}
_soft_removed_lock_per_loop: dict[int, asyncio.Lock] = {}


def get_real_columns_lock() -> asyncio.Lock:
    return get_per_loop_lock(_real_columns_lock_per_loop)


async def get_real_columns(conn: Any, table_name: str) -> frozenset[str] | None:
    """Return the actual column names present in the database for *table_name*.

    Supports SQLite, PostgreSQL, and MySQL with caching for performance.
    """
    if table_name in _REAL_COLUMNS_CACHE:
        return _REAL_COLUMNS_CACHE[table_name]

    dialect = str(conn.engine.url.drivername).lower()

    lock = get_real_columns_lock()
    async with lock:
        if table_name in _REAL_COLUMNS_CACHE:
            return _REAL_COLUMNS_CACHE[table_name]

        try:
            if "sqlite" in dialect:
                # SQLite PRAGMA does not support parameterized queries - the
                # table name must be a literal identifier.  assert_safe_table_name
                # validates the name against ^[A-Za-z_][A-Za-z0-9_$]*$ to
                # prevent SQL injection via table_name.  Double-quoting the
                # identifier provides an additional defence-in-depth layer against
                # injection even if the regex were bypassed.
                assert_safe_table_name(table_name)
                quoted = f'"{table_name}"'
                result = await conn.execute(sa.text(f"PRAGMA table_info({quoted})"))
                cols = {row[1] for row in result.fetchall()}
            elif "postgresql" in dialect:
                result = await conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :tname"
                    ),
                    {"tname": table_name},
                )
                cols = {row[0] for row in result.fetchall()}
            elif "mysql" in dialect:
                result = await conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND table_name = :tname"
                    ),
                    {"tname": table_name},
                )
                cols = {row[0] for row in result.fetchall()}
            else:
                return None

            if not cols:
                return None
            _REAL_COLUMNS_CACHE[table_name] = frozenset(cols)
            return _REAL_COLUMNS_CACHE[table_name]
        except Exception:
            logger.debug("Schema introspection failed for table %s", table_name, exc_info=True)
            return None


async def get_real_columns_bulk(
    conn: Any, table_names: list[str]
) -> dict[str, frozenset[str] | None]:
    """Fetch schema for multiple tables in parallel for better performance."""
    tasks = [get_real_columns(conn, name) for name in table_names]
    results = await asyncio.gather(*tasks)
    return dict(zip(table_names, results, strict=True))


async def preload_table_schemas() -> None:
    """Preload all table schemas into cache at startup.

    Call this during application initialization to avoid schema
    introspection overhead on first requests (~20-50% faster queries).
    """
    engine = await get_engine()
    async with engine.connect() as conn:
        table_names = [
            str(cast("Any", model_cls)._table_name)
            for model_cls in _model_registry.registry.values()
        ]
        await get_real_columns_bulk(conn, table_names)


# Sentinel stored in cache when a lookup failed, so we don't
# re-raise FieldError (and re-construct TraversalLookup) on every query.
_TRAVERSAL_FAILURE: object = object()


@functools.lru_cache(maxsize=1024)
def parse_traversal_cached(key: str, model_cls: type) -> Any:
    """Internal cached parser that returns TraversalLookup or _TRAVERSAL_FAILURE.

    LRU cache with maxsize=1024 prevents unbounded memory growth.
    """
    try:
        return TraversalLookup(key, model_cls)
    except FieldError:
        # Cache the failure sentinel so we don't retry parsing
        return _TRAVERSAL_FAILURE


def cached_traversal_lookup(key: str, model_cls: type) -> Any:
    """Return a cached TraversalLookup for *(key, model_cls)*.

    Caches both successful lookups and failures (via _TRAVERSAL_FAILURE
    sentinel) so that FieldError is only constructed once per unique
    *(key, model_cls)* pair.

    Raises FieldError if the traversal is invalid.
    """
    result = parse_traversal_cached(key, model_cls)
    if result is _TRAVERSAL_FAILURE:
        available = ", ".join(sorted(model_cls._fields))
        raise FieldError(
            f"Invalid lookup '{key}' on {model_cls.__name__}. Available fields: {available}"
        )
    return result


async def resolve_engine_for_alias(alias: str, *, write: bool = False) -> AsyncEngine:
    """Return the engine for *alias*, preserving legacy default setup."""
    try:
        backend = connections.get(alias)
    except DatabaseAliasNotFoundError:
        if alias != DEFAULT_ALIAS:
            raise
        return await get_engine()
    if write and backend.is_read_only:
        raise DatabaseReadOnlyError(f"Cannot write to read-only alias '{alias}'.")
    return await backend.create_engine()


def ensure_transaction_alias(alias: str | None) -> None:
    """Reject explicit cross-alias work inside a pinned transaction."""
    pinned_alias = _transaction_alias.get()
    if alias is not None and pinned_alias is not None and alias != pinned_alias:
        raise DatabaseTransactionRoutingError(
            f"Transaction is pinned to alias '{pinned_alias}', not '{alias}'."
        )


@asynccontextmanager
async def connect(
    alias: str | None = None,
    model_class: type | None = None,
) -> AsyncGenerator[Any]:
    """Yield a read connection, reusing a per-request connection if active.

    When a per-request connection is active, it is yielded directly.
    Otherwise a new connection is opened on the database alias resolved
    by the configured router chain (or the default alias).
    Falls back to the default engine when the connections manager is
    not configured or the resolved alias is unavailable.
    """
    ensure_transaction_alias(alias)
    req = _request_conn.get()
    if req is not None:
        yield req
    else:
        selected_alias = alias or await resolver.resolve_read(model_class or object)
        engine = await resolve_engine_for_alias(selected_alias)
        async with engine.connect() as conn:
            yield conn


@asynccontextmanager
async def begin(
    alias: str | None = None,
    model_class: type | None = None,
) -> AsyncGenerator[Any]:
    """Yield a write connection inside a transaction.

    When a per-request connection is active, a savepoint is created.
    Otherwise a new transaction is opened on the database alias resolved
    by the configured router chain (or the default alias).
    Falls back to the default engine when the connections manager is
    not configured or the resolved alias is unavailable.
    """
    ensure_transaction_alias(alias)
    req = _request_conn.get()
    if req is not None:
        if not _transaction_writes_allowed.get():
            raise DatabaseReadOnlyError("Cannot write inside a read-only database transaction.")
        async with req.begin_nested() as _:
            yield req
    else:
        selected_alias = alias or await resolver.resolve_write(model_class or object)
        engine = await resolve_engine_for_alias(selected_alias, write=True)
        async with engine.begin() as conn:
            yield conn


def get_soft_removed_lock() -> asyncio.Lock:
    """Return the per-event-loop soft-removed lock, creating it lazily."""
    return get_per_loop_lock(_soft_removed_lock_per_loop)


async def load_soft_removed_columns() -> None:
    """Load soft-removed column info from the tracking table into cache.

    Uses double-checked locking: the fast path checks the loaded flag
    without acquiring the lock.  Only when the flag is ``False`` do we acquire
    and re-check inside the lock.
    """
    # Fast path - already loaded, no lock needed.
    if _model_registry.soft_removed_loaded:
        return

    lock = get_soft_removed_lock()
    async with lock:
        if _model_registry.soft_removed_loaded:
            return
        try:
            engine = await get_engine()
            soft_table = get_soft_removed_table()
            async with engine.connect() as conn:
                exists = await conn.run_sync(
                    lambda sync_conn: sa.inspect(sync_conn).has_table(soft_table.name)
                )
                if not exists:
                    _model_registry.soft_removed_loaded = True
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
                    SOFT_REMOVED_CACHE[tname] = frozenset(cols)
            _model_registry.soft_removed_loaded = True
        except Exception:
            logger.debug("Soft-removed columns load failed; treating as empty", exc_info=True)
            _model_registry.soft_removed_loaded = True


def invalidate_soft_removed_cache() -> None:
    """Clear the soft-removed column cache (call after migrations)."""
    _model_registry.invalidate_soft_removed_cache()
    build_table.cache_clear()


def get_soft_removed_columns(table_name: str) -> frozenset[str]:
    """Return the frozenset of soft-removed column names for a table (sync).

    Must call ``load_soft_removed_columns()`` first in an async context.
    Values are ``frozenset`` so callers can iterate without holding any lock.
    """
    return SOFT_REMOVED_CACHE.get(table_name, frozenset())


_AUTH_TABLE_PLURALIZATION: dict[str, str] = {
    "auth_role": "auth_roles",
    "auth_user": "auth_users",
    "auth_permission": "auth_permissions",
    "auth_contenttype": "auth_content_types",
    "auth_content_type": "auth_content_types",
}


def resolve_fk_table_name(field: ForeignKey | OneToOneField, model_cls: type) -> str:
    """Resolve the target table name for a ForeignKey or OneToOneField.

    Tries, in order:
      1. Direct resolution via ``field.resolve_target()``
      2. Callable ``field.to`` evaluation
      3. Registry lookup by various key patterns
      4. String-based fallback heuristics
    """
    target_model_cls = field.resolve_target()

    if target_model_cls and hasattr(target_model_cls, "_table_name"):
        return str(target_model_cls._table_name)

    target_str = field.to
    if callable(target_str):
        try:
            res = target_str()
            if isinstance(res, type):
                target_model_cls = res
        except Exception:
            logger.debug("FK callable resolution failed for %s", target_str, exc_info=True)

    # Ensure target_str is a string for registry lookups and string operations
    if not isinstance(target_str, str):
        target_str = str(target_str)

    if target_str in _model_registry.registry:
        target_model_cls = cast("type", _model_registry.registry[target_str])
        return str(getattr(target_model_cls, "_table_name", ""))

    camel_to_snake = _model_registry.model_meta_cls._camel_to_snake  # type: ignore[union-attr]

    if "." in target_str:
        parts = target_str.split(".")
        model_name = parts[-1]

        app_name: str | None = None
        if "auth" in parts:
            app_name = "auth"
        elif len(parts) >= 2:
            app_name = parts[-2] if parts[-2] != "models" else parts[0]
        else:
            app_name = parts[0]

        registry_keys = [
            target_str,
            f"{app_name}.{model_name}",
            model_name,
        ]

        for key in registry_keys:
            if key in _model_registry.registry:
                target_model_cls = cast("type", _model_registry.registry[key])
                return str(getattr(target_model_cls, "_table_name", ""))

        model_snake = camel_to_snake(model_name)

        if model_name == "get_user_model" and "auth" in parts:
            return "auth_users"
        if model_name == "User" and "auth" in parts:
            return "auth_users"
        related = f"{app_name}_{model_snake}".lower()
        return _AUTH_TABLE_PLURALIZATION.get(related, related)

    model_snake = camel_to_snake(target_str)
    app_name = getattr(model_cls, "_app_name", "default")

    if app_name and app_name != "default":
        related = f"{app_name}_{model_snake}s".lower()
    else:
        related = f"{model_snake}s".lower()

    return _AUTH_TABLE_PLURALIZATION.get(related, related)


@functools.lru_cache(maxsize=256)
def build_table(table_name: str, model_cls: type) -> sa.Table:
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
            continue  # ManyToMany - no column

        col_name = field.column_name
        if col_name in added_columns:
            continue

        col_type = sa_type(field)
        args: list[Any] = [col_name, col_type]

        # Add ForeignKey constraint if applicable
        if isinstance(field, (ForeignKey, OneToOneField)):
            related_table = resolve_fk_table_name(field, model_cls)
            if related_table:
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

    # Add composite indexes and unique constraints from Meta
    table_args: list[Any] = list(columns)
    for idx in getattr(model_cls, "_meta_indexes", []):
        col_names = [
            model_cls._fields[f].column_name if f in model_cls._fields else f for f in idx.fields
        ]
        index_name = idx.name or f"idx_{table_name}_{'_'.join(col_names)}"
        table_args.append(sa.Index(index_name, *col_names))

    for ut_fields in getattr(model_cls, "_meta_unique_together", []):
        col_names = [
            model_cls._fields[f].column_name if f in model_cls._fields else f for f in ut_fields
        ]
        table_args.append(sa.UniqueConstraint(*col_names))

    return sa.Table(table_name, metadata, *table_args, extend_existing=True)


def get_table(model_cls: type[Model]) -> sa.Table:
    """Return (or lazily build) the SQLAlchemy Table for a model class."""
    return build_table(model_cls._table_name, model_cls)


def sa_type(field: Any) -> sa.types.TypeEngine[Any]:
    if hasattr(field, "get_sa_type"):
        return cast("sa.types.TypeEngine[Any]", field.get_sa_type())
    if isinstance(field, AutoField):
        return sa.Integer()
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
                        return sa.UUID(as_uuid=True)
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
        return sa.DateTime(timezone=True)
    if isinstance(field, DateField):
        return sa.Date()
    if isinstance(field, TimeField):
        return sa.Time()
    if isinstance(field, UUIDField):
        return sa.UUID(as_uuid=True)
    if isinstance(field, JSONField):
        return sa.JSON()
    if isinstance(field, FileField):
        return sa.String(field.max_length)
    if isinstance(field, CharField):
        return sa.String(field.max_length)
    return sa.Text()


def build_traversal_joins(
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

    # Track the "left" table for each step - the table that owns the FK column.
    # For the first step this is the base table; for subsequent steps it is
    # the target table resolved by the previous step.  This avoids ambiguous
    # column lookups on SQLAlchemy JOIN objects where multiple tables may
    # share column names (e.g. "id" or "reporter_id").
    left_table: sa.Table = base_table

    # Build JOINs for each FK step
    for _i, step in enumerate(join_steps):
        # Get the FK field's column on the left (owning) table
        fk_column = step.field.column_name
        if fk_column not in left_table.c:
            # Try with _id suffix if needed
            if f"{step.field.name}_id" in left_table.c:
                fk_column = f"{step.field.name}_id"
            else:
                raise ValueError(f"Cannot find FK column '{fk_column}' on table")

        # Get the related model's table
        related_model = step.field.resolve_target()
        related_table = get_table(related_model)

        # Build JOIN condition: left_table.fk_id == related_table.id
        join_condition = left_table.c[fk_column] == related_table.c.id

        # Create LEFT OUTER JOIN to support NULL foreign keys
        from_clause = from_clause.outerjoin(related_table, join_condition)

        # Next step's FK column lives in this step's target table
        left_table = related_table

    # Get final table (last target in the traversal)
    return from_clause, get_table(traversal.final_model)


def compile_traversal_filter(
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
        lookup_obj = cached_traversal_lookup(key, model_cls)
    except FieldError:
        # Invalid traversal, return None (filter ignored)
        return None, []

    if lookup_obj.is_simple_field():
        # Not a traversal, compile normally
        col_name = lookup_obj.final_field.column_name
        if col_name not in base_table.c and f"{col_name}_id" in base_table.c:
            col_name = f"{col_name}_id"
        col = base_table.c[col_name]
        where_clause = apply_lookup(col, "", value, field=lookup_obj.final_field)
        return where_clause, []

    # Build JOINs for traversal
    from_clause, final_table = build_traversal_joins(lookup_obj, base_table)

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
    where_clause = apply_lookup(col, lookup, value, field=final_field)

    # Collect all JOINs from the from_clause
    # The from_clause is a join with multiple tables, we need to extract it
    joins = [from_clause] if from_clause != base_table else []

    return where_clause, joins


def escape_like(value: object) -> str:
    """Escape LIKE metacharacters (% and _) in user-provided values.

    Prevents LIKE injection attacks where malicious input like '%' could
    match all rows or '%%' could cause expensive pattern matching.
    """
    str_value: str = value if isinstance(value, str) else str(value)
    # Escape backslash first (it's the escape character), then % and _
    return str_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_lookup(
    col: sa.ColumnElement[Any], lookup: str, value: object, field: object = None
) -> sa.ColumnElement[Any]:
    """Apply a lookup operator to a column."""
    # Use Field.to_db() if available to prepare the value for the database.
    # This respects field-specific logic like DateTime timezones or Boolean mappings.
    if field is not None:
        try:
            if lookup in ("in", "not_in") and isinstance(value, (list, tuple)):
                value = [field.to_db(v) for v in value]
            else:
                value = field.to_db(value)
        except ValueError:
            return sa.false()
        except TypeError:
            return sa.false()

    # Unwrap LazyFK values to raw IDs for SQL binding
    if isinstance(value, LazyFK):
        value = value.fk_id
    # Unwrap Model instances to their primary key for FK filter comparisons
    if hasattr(value, "_meta_table_name") or (
        hasattr(value, "__class__") and hasattr(value.__class__, "_fields")
    ):
        value = getattr(value, "id", value)
    # Intercept UUID columns to ensure they get a uuid.UUID object

    is_uuid_col = (
        hasattr(col, "type") and isinstance(col.type, Uuid) and getattr(col.type, "as_uuid", True)
    )

    if is_uuid_col:
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                value = uuid.UUID(value)
    else:
        # For non-UUID columns, convert UUID objects to strings for database comparison
        if isinstance(value, uuid.UUID):
            value = str(value)

    if is_uuid_col and isinstance(value, uuid.UUID):
        if lookup in ("exact", ""):
            return col == value
        if lookup == "ne":
            return col != value
        if lookup == "isnull":
            return col.is_(None) if value else col.isnot(None)

    if lookup in ("exact", ""):
        return col == value
    if lookup == "ne":
        return col != value
    if lookup == "contains":
        escaped_value = escape_like(value)
        return col.like(f"%{escaped_value}%", escape="\\")
    if lookup == "icontains":
        escaped_value = escape_like(value)
        return col.ilike(f"%{escaped_value}%", escape="\\")
    if lookup == "startswith":
        escaped_value = escape_like(value)
        return col.like(f"{escaped_value}%", escape="\\")
    if lookup == "endswith":
        escaped_value = escape_like(value)
        return col.like(f"%{escaped_value}", escape="\\")
    if lookup == "gt":
        return col > value
    if lookup == "gte":
        return col >= value
    if lookup == "lt":
        return col < value
    if lookup == "lte":
        return col <= value
    if lookup == "in":
        if isinstance(value, (list, tuple)):
            unwrapped = [
                (
                    v.fk_id
                    if isinstance(v, LazyFK)
                    else getattr(v, "id", v) if hasattr(v.__class__, "_fields") else v
                )
                for v in value
            ]
            return col.in_(unwrapped)
        return col.in_(cast("list[object]", value))
    if lookup == "not_in":
        if isinstance(value, (list, tuple)):
            unwrapped = [
                (
                    v.fk_id
                    if isinstance(v, LazyFK)
                    else getattr(v, "id", v) if hasattr(v.__class__, "_fields") else v
                )
                for v in value
            ]
            return col.notin_(unwrapped)
        return col.notin_(cast("list[object]", value))
    if lookup == "isnull":
        return col.is_(None) if value else col.isnot(None)
    if lookup == "range":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            lo, hi = value
            return col.between(lo, hi)
        return sa.false()
    if lookup == "iexact":
        return cast("sa.ColumnElement[Any]", sa.func.lower(col) == cast("str", value).lower())
    if lookup == "istartswith":
        escaped_value = escape_like(value)
        return col.ilike(f"{escaped_value}%", escape="\\")
    if lookup == "iendswith":
        escaped_value = escape_like(value)
        return col.ilike(f"%{escaped_value}", escape="\\")
    if lookup == "regex":
        if isinstance(value, str):
            validate_regex_pattern(value)
        return col.regexp_match(value)
    if lookup == "iregex":
        if isinstance(value, str):
            validate_regex_pattern(value)
        return col.regexp_match(value, flags="i")
    if lookup == "date":
        return cast("sa.ColumnElement[Any]", sa.cast(col, sa.Date) == value)
    if lookup == "year":
        return cast("sa.ColumnElement[Any]", sa.extract("year", col) == value)
    if lookup == "month":
        return cast("sa.ColumnElement[Any]", sa.extract("month", col) == value)
    if lookup == "day":
        return cast("sa.ColumnElement[Any]", sa.extract("day", col) == value)
    raise FieldError(f"Unsupported lookup type: '{lookup}'")


def compile_single_filter(
    table: sa.Table, key: str, value: object, model_cls: type | None = None
) -> sa.ColumnElement[Any] | None:
    """Compile one ``field__lookup=value`` pair to a SQLAlchemy clause.

    This is the legacy interface that returns only the WHERE clause.
    For traversal support with JOINs, use execute_select directly.
    """
    parts = key.split("__", 1)
    col_name = parts[0]
    lookup = parts[1] if len(parts) > 1 else "exact"

    # Resolve 'pk' to the actual primary key column name
    if col_name == "pk":
        pk_cols = list(table.primary_key.columns)
        col_name = pk_cols[0].name if pk_cols else "id"

    # Support FK _id column aliases (e.g. filter(author=5) -> author_id column)
    if col_name not in table.c and f"{col_name}_id" in table.c:
        col_name = f"{col_name}_id"

    if col_name not in table.c:
        return None

    col = table.c[col_name]

    # Resolve the field from model_cls if available to enable field-aware prep in apply_lookup
    field = None
    if model_cls and hasattr(model_cls, "_fields"):
        # For FKs, the column might be 'author_id' but the field is 'author'
        lookup_name = col_name
        if lookup_name not in model_cls._fields and lookup_name.endswith("_id"):
            base_name = lookup_name[:-3]
            if base_name in model_cls._fields:
                lookup_name = base_name
        field = model_cls._fields.get(lookup_name)

    return apply_lookup(col, lookup, value, field=field)


def compile_q(table: sa.Table, q_obj: Any) -> sa.ColumnElement[Any] | None:
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
            clause = compile_single_filter(table, key, value)
        else:
            clause = compile_q(table, child)
        if clause is not None:
            clauses.append(clause)

    if not clauses:
        return None

    combined: sa.ColumnElement[Any] = (
        sa.or_(*clauses) if getattr(q_obj, "connector", "AND") == "OR" else sa.and_(*clauses)
    )
    return sa.not_(combined) if getattr(q_obj, "negated", False) else combined


def compile_q_with_traversals(
    model_cls: type,
    base_table: sa.Table,
    q_obj: Any,
    collected_joins: dict[str, tuple[sa.FromClause, sa.Table]],
    from_clause_box: list[sa.FromClause],
) -> sa.ColumnElement[Any] | None:
    """Recursively compile a Q object to a SQLAlchemy clause with FK traversal support.

    Duck-typed against :class:`~openviper.db.models.Q` without a circular
    import.  ``from_clause_box`` is a single-element list used as a mutable
    reference: the caller reads ``from_clause_box[0]`` after this call to
    obtain the (possibly extended) FROM clause when traversal JOINs were added.
    """
    if not q_obj.children:
        return None

    clauses: list[sa.ColumnElement[Any]] = []
    for child in q_obj.children:
        if isinstance(child, tuple):
            key, value = child
            try:
                traversal = cached_traversal_lookup(key, model_cls)
                if not traversal.is_simple_field():
                    if key in collected_joins:
                        _cached_from, final_table = collected_joins[key]
                    else:
                        traversal_from, final_table = build_traversal_joins(traversal, base_table)
                        collected_joins[key] = (traversal_from, final_table)
                        from_clause_box[0] = traversal_from
                    col = final_table.c[traversal.final_field.column_name]
                    clause: sa.ColumnElement[Any] | None = apply_lookup(
                        col, "", value, field=traversal.final_field
                    )
                    if clause is not None:
                        clauses.append(clause)
                    continue
            except FieldError:
                pass
            clause = compile_single_filter(base_table, key, value, model_cls=model_cls)
            if clause is not None:
                clauses.append(clause)
        else:
            clause = compile_q_with_traversals(
                model_cls, base_table, child, collected_joins, from_clause_box
            )
            if clause is not None:
                clauses.append(clause)

    if not clauses:
        return None

    combined: sa.ColumnElement[Any] = (
        sa.or_(*clauses) if getattr(q_obj, "connector", "AND") == "OR" else sa.and_(*clauses)
    )
    return sa.not_(combined) if getattr(q_obj, "negated", False) else combined


def compile_filters(
    table: sa.Table, filter_dicts: list[dict[str, object]]
) -> sa.ColumnElement[Any] | None:
    """Convert ORM filter dicts to an ANDed SQLAlchemy clause."""
    clauses: list[sa.ColumnElement[Any]] = []
    for filters in filter_dicts:
        for key, value in filters.items():
            clause = compile_single_filter(table, key, value)
            if clause is None:
                col_name = key.split("__")[0]
                if col_name == "pk":
                    col_name = "pk (primary key)"
                available = ", ".join(sorted(table.c.keys()))
                raise FieldError(
                    f"Invalid filter key '{key}': column '{col_name}' does not exist"
                    f" in table '{table.name}'."
                    f" Available columns: {available}"
                )
            clauses.append(clause)
    return sa.and_(*clauses) if clauses else None


def compile_excludes(
    table: sa.Table, exclude_dicts: list[dict[str, object]]
) -> sa.ColumnElement[Any] | None:
    filters_clause = compile_filters(table, exclude_dicts)
    if filters_clause is None:
        return None
    return sa.not_(filters_clause)


def build_where_clause(
    table: sa.Table,
    filter_dicts: list[dict[str, object]],
    exclude_dicts: list[dict[str, object]],
    q_filters: list[Any],
) -> sa.ColumnElement[Any] | None:
    """Combine filter dicts, exclude dicts, and Q objects into one WHERE clause."""
    parts: list[sa.ColumnElement[Any]] = []
    f = compile_filters(table, filter_dicts)
    if f is not None:
        parts.append(f)
    e = compile_excludes(table, exclude_dicts)
    if e is not None:
        parts.append(e)
    for q_obj in q_filters:
        q_clause = compile_q(table, q_obj)
        if q_clause is not None:
            parts.append(q_clause)
    return sa.and_(*parts) if parts else None


def build_where_clause_with_traversals(
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
                traversal = cached_traversal_lookup(key, model_cls)
                if not traversal.is_simple_field():
                    # Check join cache before building to avoid redundant work
                    if key in collected_joins:
                        traversal_from, final_table = collected_joins[key]
                    else:
                        traversal_from, final_table = build_traversal_joins(traversal, base_table)
                        collected_joins[key] = (traversal_from, final_table)
                        # Accumulate traversal JOINs into the shared from_clause
                        # so that multiple FK traversals are all present.
                        if traversal_from is not base_table:
                            from_clause = (
                                from_clause.join(
                                    final_table,
                                    from_clause.c[
                                        traversal.get_joins_needed()[-1].field.column_name
                                    ]
                                    == final_table.c.id,
                                    isouter=True,
                                )
                                if from_clause is not base_table
                                else traversal_from
                            )

                    # Compile filter on final table
                    col = final_table.c[traversal.final_field.column_name]
                    clause = apply_lookup(col, "", value, field=traversal.final_field)
                    if clause is not None:
                        parts.append(clause)
                    continue
            except FieldError:
                pass

            # Normal field compilation fallback
            fallback_clause = compile_single_filter(base_table, key, value, model_cls=model_cls)
            if fallback_clause is None:
                available = ", ".join(sorted(model_cls._fields))
                raise FieldError(
                    f"Invalid filter key '{key}': field '{key.split('__')[0]}'"
                    f" does not exist on {model_cls.__name__}."
                    f" Available fields: {available}"
                )
            parts.append(fallback_clause)

    # Process excludes (can also use traversals)
    for excludes in exclude_dicts:
        for key, value in excludes.items():
            try:
                traversal = cached_traversal_lookup(key, model_cls)
                if not traversal.is_simple_field():
                    if key in collected_joins:
                        traversal_from, final_table = collected_joins[key]
                    else:
                        traversal_from, final_table = build_traversal_joins(traversal, base_table)
                        collected_joins[key] = (traversal_from, final_table)
                        if traversal_from is not base_table:
                            from_clause = (
                                from_clause.join(
                                    final_table,
                                    from_clause.c[
                                        traversal.get_joins_needed()[-1].field.column_name
                                    ]
                                    == final_table.c.id,
                                    isouter=True,
                                )
                                if from_clause is not base_table
                                else traversal_from
                            )

                    col = final_table.c[traversal.final_field.column_name]
                    clause = apply_lookup(col, "", value, field=traversal.final_field)
                    if clause is not None:
                        parts.append(sa.not_(clause))
                    continue
            except FieldError:
                pass

            # Normal exclude fallback
            fallback_exclude = compile_single_filter(base_table, key, value, model_cls=model_cls)
            if fallback_exclude is None:
                available = ", ".join(sorted(model_cls._fields))
                raise FieldError(
                    f"Invalid exclude key '{key}': field '{key.split('__')[0]}'"
                    f" does not exist on {model_cls.__name__}."
                    f" Available fields: {available}"
                )
            parts.append(sa.not_(fallback_exclude))

    # Q objects - with traversal support
    for q_obj in q_filters:
        from_clause_box: list[sa.FromClause] = [from_clause]
        q_clause = compile_q_with_traversals(
            model_cls, base_table, q_obj, collected_joins, from_clause_box
        )
        from_clause = from_clause_box[0]
        if q_clause is not None:
            parts.append(q_clause)

    where_clause = sa.and_(*parts) if parts else None
    return where_clause, from_clause


def is_f_like(v: object) -> bool:
    """Return True if *v* is an F or _FExpr (duck-typed, no import)."""
    return (
        hasattr(v, "name")
        and not hasattr(v, "lhs")
        and not hasattr(v, "func")
        or (hasattr(v, "lhs") and hasattr(v, "op") and hasattr(v, "rhs"))
    )


def f_expr_as_sa(table: sa.Table, expr: object) -> sa.ColumnElement[Any] | None:
    """Convert an F reference or _FExpr arithmetic tree to a SQLAlchemy expression.

    Duck-typed: works without importing F / _FExpr from models to avoid circulars.
    Returns ``None`` when the field cannot be resolved.
    """
    # _FExpr (has lhs/op/rhs)
    if hasattr(expr, "lhs") and hasattr(expr, "op") and hasattr(expr, "rhs"):
        lhs = f_expr_as_sa(table, expr.lhs) if is_f_like(expr.lhs) else expr.lhs
        rhs = f_expr_as_sa(table, expr.rhs) if is_f_like(expr.rhs) else expr.rhs
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


def ann_expr_as_sa(table: sa.Table, expr: object) -> sa.ColumnElement[Any] | None:
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
        return cast("sa.ColumnElement[Any]", sa_func(col))

    # F or _FExpr
    if is_f_like(expr):
        return f_expr_as_sa(table, expr)

    return None


async def execute_select(qs: QuerySet) -> list[dict[str, Any]]:
    model_cls = qs._model
    table = get_table(model_cls)

    # ── Column selection (only / defer) ───────────────────────────────────
    only_fields: set[str] = set(getattr(qs, "_only_fields", []))
    defer_fields: set[str] = set(getattr(qs, "_defer_fields", []))

    # ── select_related JOINs ──────────────────────────────────────────────
    from_clause: Any = table
    extra_cols: list[Any] = []

    # Collect related tables first so all column checks share one connection.
    related_info: list[tuple[str, Any]] = []
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
        related_info.append((field_name, related_table))

    # ── WHERE + traversal JOINs (chains off any select_related joins) ─────
    q_filters = getattr(qs, "_q_filters", [])
    where, from_clause = build_where_clause_with_traversals(
        model_cls,
        table,
        qs._filters,
        qs._excludes,
        q_filters,
        initial_from_clause=from_clause,
    )

    # Use a single connection for all schema-resilience checks and query execution.
    async with connect(qs._db_alias, model_cls) as conn:
        # Parallel schema resilience: check all table columns at once
        all_table_names = [related_table.name for _, related_table in related_info] + [table.name]
        schema_results = await get_real_columns_bulk(conn, all_table_names)

        # Schema resilience: check related table columns
        for field_name, related_table in related_info:
            real_cols = schema_results.get(related_table.name)

            # Respect only/defer for related columns if specified via "relation__field"
            prefix = f"{field_name}__"
            for col in related_table.c:
                if real_cols is not None and col.name not in real_cols:
                    continue

                label = f"{prefix}{col.name}"
                if (
                    only_fields
                    and label not in only_fields
                    and col.name != "id"
                    or defer_fields
                    and label in defer_fields
                ):
                    continue
                extra_cols.append(col.label(label))

        # Schema resilience: base table columns
        base_real_cols = schema_results.get(table.name)

        if only_fields:
            wanted: set[str] = only_fields | {"id"}
            base_cols: list[Any] = [
                col
                for col in table.c
                if col.name in wanted and (base_real_cols is None or col.name in base_real_cols)
            ]
        elif defer_fields:
            deferred: set[str] = {
                (model_cls._fields[f].column_name if f in model_cls._fields else f)
                for f in defer_fields
            }
            base_cols = [
                col
                for col in table.c
                if col.name not in deferred
                and (base_real_cols is None or col.name in base_real_cols)
            ]
        else:
            base_cols = [
                col for col in table.c if base_real_cols is None or col.name in base_real_cols
            ]

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
                if (sa_expr := ann_expr_as_sa(table, expr)) is not None
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
        _effective_limit = qs._limit if qs._limit is not None else max_query_rows()
        if _effective_limit is not None:
            stmt = stmt.limit(_effective_limit)
        if qs._offset is not None:
            stmt = stmt.offset(qs._offset)

        # ── SELECT FOR UPDATE ─────────────────────────────────────────────────
        if getattr(qs, "_for_update", False):
            nowait: bool = getattr(qs, "_for_update_nowait", False)
            skip_locked: bool = getattr(qs, "_for_update_skip_locked", False)
            stmt = stmt.with_for_update(nowait=nowait, skip_locked=skip_locked)

        # ── Query result cache ────────────────────────────────────────────────
        # Only cache read-only queries (no FOR UPDATE) on models with cache_ttl.
        cache_ttl: float = getattr(model_cls, "_cache_ttl", 0)
        cache_key: str | None = None
        if cache_ttl > 0 and not getattr(qs, "_for_update", False):
            try:
                cache_key = cache_key_for_stmt(model_cls._table_name, stmt)
                cached = get_query_cache().get(cache_key)
                if cached is not None:
                    return cached
            except Exception:
                logger.debug("Query cache key generation failed", exc_info=True)
                cache_key = None

        try:
            result = await conn.execute(stmt)
            rows = [dict(row) for row in result.mappings()]
            if cache_key is not None:
                get_query_cache().put(cache_key, rows, cache_ttl)
            return rows
        except SADBAPIError as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            # Invalid parameter values (e.g. malformed UUID, wrong type) mean no
            # matching row can exist - treat as an empty result set rather than
            # propagating a 500 error.
            if is_data_error(e):
                logger.debug(
                    "SELECT query returned no results due to invalid parameter for model %s: %s",
                    model_cls.__name__,
                    str(e),
                )
                return []
            logger.error(
                "SELECT query failed for model %s: %s",
                model_cls.__name__,
                str(e),
                exc_info=True,
                extra={
                    "model": model_cls.__name__,
                    "filters": redact_filters(qs._filters),
                    "excludes": redact_filters(qs._excludes),
                },
            )
            raise
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            logger.error(
                "SELECT query failed for model %s: %s",
                model_cls.__name__,
                str(e),
                exc_info=True,
                extra={
                    "model": model_cls.__name__,
                    "filters": redact_filters(qs._filters),
                    "excludes": redact_filters(qs._excludes),
                },
            )
            raise


async def execute_count(qs: QuerySet) -> int:
    model_cls = qs._model
    table = get_table(model_cls)

    q_filters = getattr(qs, "_q_filters", [])
    where, from_clause = build_where_clause_with_traversals(
        model_cls, table, qs._filters, qs._excludes, q_filters
    )

    stmt = (
        sa.select(sa.func.count()).select_from(from_clause)
        if from_clause is not table
        else sa.select(sa.func.count()).select_from(table)
    )
    if where is not None:
        stmt = stmt.where(where)

    async with connect(qs._db_alias, model_cls) as conn:
        try:
            result = await conn.execute(stmt)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            raise
        return int(result.scalar_one())


async def execute_exists(qs: QuerySet) -> bool:
    """Check existence with SELECT 1 ... LIMIT 1 - stops at the first match."""
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(sa.literal(1)).select_from(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    stmt = stmt.limit(1)

    async with connect(qs._db_alias, model_cls) as conn:
        try:
            result = await conn.execute(stmt)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            raise
        return result.first() is not None


async def execute_delete(qs: QuerySet) -> int:
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.delete(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    try:
        async with begin(qs._db_alias, model_cls) as conn:
            result = await conn.execute(stmt)
            get_query_cache().invalidate_model(model_cls._table_name)
            return int(result.rowcount)
    except Exception as e:
        check_table_missing(e, model_cls)
        check_field_missing(e, model_cls)
        logger.error(
            "Bulk DELETE failed for model %s: %s",
            model_cls.__name__,
            str(e),
            exc_info=True,
            extra={
                "model": model_cls.__name__,
                "filters": redact_filters(qs._filters),
                "excludes": redact_filters(qs._excludes),
            },
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
        if is_f_like(v):
            # F / _FExpr - resolve column reference(s) directly
            col_name = field_def.column_name if field_def else k
            sa_expr = f_expr_as_sa(table, v)
            if sa_expr is not None:
                db_values[col_name] = sa_expr
        elif field_def is not None:
            db_values[field_def.column_name] = field_def.to_db(v)
        else:
            db_values[k] = v

    stmt = sa.update(table).values(**db_values)

    q_filters = getattr(qs, "_q_filters", [])
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    try:
        async with begin(qs._db_alias, model_cls) as conn:
            result = await conn.execute(stmt)
            get_query_cache().invalidate_model(model_cls._table_name)
            return int(result.rowcount)
    except Exception as e:
        check_table_missing(e, model_cls)
        check_field_missing(e, model_cls)
        logger.error(
            "Bulk UPDATE failed for model %s: %s",
            model_cls.__name__,
            str(e),
            exc_info=True,
            extra={
                "model": model_cls.__name__,
                "filters": redact_filters(qs._filters),
                "values": redact_values(values),
            },
        )
        raise


async def execute_save(
    instance: Model,
    ignore_permissions: bool = False,
    update_fields: list[str] | None = None,
) -> None:
    """INSERT or UPDATE a single model instance.

    Args:
        instance: The model instance to persist.
        ignore_permissions: Skip permission checks when ``True``.
        update_fields: When provided on an UPDATE, only these field names are
            written to the database.  Ignored on INSERT.  Raises
            :exc:`ValueError` if a name is not a known field on the model.
    """
    model_cls = type(instance)
    action = "update" if getattr(instance, "pk", None) else "create"
    # Honour both the ContextVar (preferred) and the legacy flag
    skip = ignore_permissions or _bypass_permissions.get()
    await check_permission_for_model(model_cls, action, ignore_permissions=skip)

    table = get_table(model_cls)
    instance._apply_auto_fields()

    # Load soft-removed columns so we can skip them during save.
    await load_soft_removed_columns()
    soft_removed = get_soft_removed_columns(model_cls._table_name)

    # Fast path: if no soft-removed columns, avoid membership checks in loop
    has_soft_removed = bool(soft_removed)

    # Validate update_fields names before touching the DB.
    if update_fields is not None:
        unknown = [f for f in update_fields if f not in model_cls._fields]
        if unknown:
            raise ValueError(
                f"update_fields contains unknown field(s) for {model_cls.__name__}: {unknown!r}"
            )
        # Normalise to a frozenset for O(1) membership checks below.
        _update_fields: frozenset[str] | None = frozenset(update_fields)
    else:
        _update_fields = None

    data = {}
    for name, field in model_cls._fields.items():
        if isinstance(field, ManyToManyField):
            continue

        val = getattr(instance, name)
        await field.pre_save(instance, val)
        # Re-fetch value in case pre_save modified it (e.g. UploadFile -> str path)
        val = getattr(instance, name)

        if field.primary_key and field.auto_increment and val is None:
            continue
        if has_soft_removed and field.column_name in soft_removed:
            continue
        # When update_fields is set on an UPDATE, skip fields not in the list.
        # Always include all fields for INSERT.
        if _update_fields is not None and name not in _update_fields:
            continue
        data[field.column_name] = field.to_db(val)

    pk_val = getattr(instance, "id", None)
    # _persisted is authoritative: False means the instance has never been saved,
    # regardless of whether a PK is already set (UUID, string, user-assigned int).
    is_new = not getattr(instance, "_persisted", False)

    if is_new:
        stmt = sa.insert(table).values(**data)
        try:
            async with begin(model_class=model_cls) as conn:
                result = await conn.execute(stmt)
                # Only update instance.id if it's not already set (for auto-increment)
                if pk_val is None:
                    instance.id = cast("Any", result).inserted_primary_key[0]
            instance._persisted = True
            get_query_cache().invalidate_model(model_cls._table_name)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            logger.error(
                "INSERT failed for model %s: %s",
                model_cls.__name__,
                str(e),
                exc_info=True,
            )
            raise
    else:
        # Primary key columns must never appear in the SET clause - they belong
        # only in the WHERE predicate.  Remove them regardless of how they ended
        # up in `data` (e.g. UUID PKs are not auto-increment so the loop above
        # does not skip them).
        pk_columns = {f.column_name for f in model_cls._fields.values() if f.primary_key}
        update_data = {k: v for k, v in data.items() if k not in pk_columns}
        upd_stmt = sa.update(table).where(table.c.id == pk_val).values(**update_data)
        try:
            async with begin(model_class=model_cls) as conn:
                result = await conn.execute(upd_stmt)
                # When no rows were updated and no specific fields were requested,
                # the row may have been deleted between the SELECT and UPDATE.
                # Do NOT fall back to INSERT - that would bypass row-level
                # security policies and could resurrect deleted rows.
                if result.rowcount == 0 and _update_fields is None:
                    logger.warning(
                        "UPDATE matched 0 rows for %s pk=%s; "
                        "row may have been deleted concurrently",
                        model_cls.__name__,
                        pk_val,
                    )
            instance._persisted = True
            get_query_cache().invalidate_model(model_cls._table_name)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
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
        async with begin(model_class=model_cls) as conn:
            await conn.execute(sa.delete(table).where(table.c.id == pk_val))
        get_query_cache().invalidate_model(model_cls._table_name)
    except Exception as e:
        check_table_missing(e, model_cls)
        check_field_missing(e, model_cls)
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

    Supports traversal field names (e.g. ``"user__username"``) which trigger
    LEFT OUTER JOINs through ForeignKey relationships so that related-model
    columns can be selected alongside local columns.

    Traversal keys are remapped to their final field name in the output:
    ``"user__username"`` becomes ``"username"``.  When two traversal fields
    share the same final name (e.g. ``"author__name"`` and ``"editor__name"``),
    the full traversal key is preserved to avoid collision.

    Example::

        rows = await Score.objects.order_by("-score").limit(5).values(
            "user__username", "score", "mode"
        )
        # [{"username": "alice", "score": 100, "mode": "hard"}, ...]

    Annotations from ``qs._annotations`` are included as extra columns.
    """
    model_cls = qs._model
    table = get_table(model_cls)

    annotations: dict[str, Any] = getattr(qs, "_annotations", {})

    # ── Classify fields into simple / traversal / annotation ──────────────
    traversal_fields: list[str] = []
    simple_fields: list[str] = []
    has_traversal = False

    if fields:
        for fname in fields:
            if fname in annotations:
                continue  # annotation - handled below
            if "__" in fname:
                traversal_fields.append(fname)
                has_traversal = True
            else:
                simple_fields.append(fname)

    # Detect traversal in order_by that isn't covered by field traversal.
    order_traversal_fields: list[str] = []
    for ofield in qs._order:
        col_name = ofield.lstrip("-")
        if "__" in col_name and col_name not in traversal_fields:
            order_traversal_fields.append(col_name)
            has_traversal = True

    # ── Build JOINs & column list ─────────────────────────────────────────
    from_clause: sa.FromClause = table
    wanted_cols: list[Any] = []

    # Track joined FK paths to avoid duplicate JOINs when multiple traversal
    # fields share the same FK prefix (e.g. "user__username" and "user__email").
    # Key: (left_table_name, fk_column_name) → right_table
    joined_fks: dict[tuple[str, str], sa.Table] = {}

    # All traversal paths that need JOINs (from both fields and order_by).
    all_traversal: list[str] = sorted(
        set(traversal_fields) | set(order_traversal_fields),
        key=lambda k: k.count("__"),
    )
    traversal_lookups: dict[str, Any] = {}

    if all_traversal:
        # Parse and validate traversal fields (sorted by depth so
        # shallower paths are joined before deeper ones that depend on them).
        for fname in all_traversal:
            try:
                traversal = cached_traversal_lookup(fname, model_cls)
            except FieldError:
                available = sorted(model_cls._fields.keys())
                raise FieldError(
                    f"Invalid traversal field '{fname}' for model {model_cls.__name__}."
                    f" Available fields: {', '.join(available)}"
                ) from None
            traversal_lookups[fname] = traversal

            # Build JOINs for each FK step in the traversal path.
            left_table: sa.Table = table
            for step in traversal.get_joins_needed():
                fk_key = (left_table.name, step.field.column_name)
                if fk_key in joined_fks:
                    left_table = joined_fks[fk_key]
                    continue

                related_model = step.field.resolve_target()
                related_table = get_table(related_model)

                fk_col = step.field.column_name
                if fk_col not in left_table.c:
                    alt = f"{step.field.name}_id"
                    if alt in left_table.c:
                        fk_col = alt
                    else:
                        raise ValueError(
                            f"Cannot find FK column '{step.field.column_name}' "
                            f"on table '{left_table.name}'"
                        )

                from_clause = from_clause.outerjoin(
                    related_table,
                    left_table.c[fk_col] == related_table.c.id,
                )
                joined_fks[fk_key] = related_table
                left_table = related_table

    if fields:
        # Build the SELECT column list.
        field_defs = model_cls._fields
        available = sorted(field_defs.keys())
        for fname in fields:
            if fname in annotations:
                sa_expr = ann_expr_as_sa(table, annotations[fname])
                if sa_expr is not None:
                    wanted_cols.append(sa_expr.label(fname))
            elif fname in traversal_fields:
                traversal = traversal_lookups[fname]
                final_table = get_table(traversal.final_model)
                col_name = traversal.final_field.column_name
                if col_name not in final_table.c:
                    # Try the field name itself as fallback
                    if traversal.final_field.name in final_table.c:
                        col_name = traversal.final_field.name
                    else:
                        raise FieldError(
                            f"Column '{col_name}' not found on table "
                            f"'{final_table.name}' for traversal field '{fname}'."
                        )
                wanted_cols.append(final_table.c[col_name].label(fname))
            else:
                field_def = field_defs.get(fname)
                col_name = field_def.column_name if field_def else fname
                if col_name not in table.c:
                    raise FieldError(
                        f"Invalid field '{fname}' for model {model_cls.__name__}."
                        f" Available fields: {', '.join(available)}"
                    )
                wanted_cols.append(table.c[col_name].label(fname))

        stmt = sa.select(*wanted_cols) if wanted_cols else sa.select(table)
        if from_clause is not table:
            stmt = stmt.select_from(from_clause)
    else:
        ann_cols = [
            sa_expr.label(alias)
            for alias, expr in annotations.items()
            if (sa_expr := ann_expr_as_sa(table, expr)) is not None
        ]
        stmt = sa.select(*table.c, *ann_cols) if ann_cols else sa.select(table)

    # ── WHERE clause - use traversal-aware builder when JOINs are present ─
    q_filters = getattr(qs, "_q_filters", [])
    if has_traversal or from_clause is not table:
        where, from_clause = build_where_clause_with_traversals(
            model_cls,
            table,
            qs._filters,
            qs._excludes,
            q_filters,
            initial_from_clause=from_clause,
        )
        if from_clause is not table and fields is None:
            # Re-build select with the correct from_clause when WHERE
            # traversals added JOINs but no explicit fields were given.
            ann_cols = [
                sa_expr.label(alias)
                for alias, expr in annotations.items()
                if (sa_expr := ann_expr_as_sa(table, expr)) is not None
            ]
            stmt = (
                sa.select(*table.c, *ann_cols).select_from(from_clause)
                if ann_cols
                else sa.select(table).select_from(from_clause)
            )
        elif from_clause is not table and fields is not None:
            # The from_clause may have been extended by the WHERE traversal
            # builder - rebuild the statement with the updated from_clause.
            stmt = (
                sa.select(*wanted_cols).select_from(from_clause)
                if wanted_cols
                else sa.select(table)
            )
    else:
        where = build_where_clause(table, qs._filters, qs._excludes, q_filters)

    if where is not None:
        stmt = stmt.where(where)

    for field_name in qs._order:
        desc = field_name.startswith("-")
        col_name = field_name.lstrip("-")
        if col_name in table.c:
            col = table.c[col_name]
            stmt = stmt.order_by(col.desc() if desc else col.asc())
        elif "__" in col_name and col_name in traversal_lookups:
            traversal = traversal_lookups[col_name]
            order_table = get_table(traversal.final_model)
            order_col_name = traversal.final_field.column_name
            if order_col_name in order_table.c:
                col = order_table.c[order_col_name]
                stmt = stmt.order_by(col.desc() if desc else col.asc())

    if getattr(qs, "_distinct", False):
        stmt = stmt.distinct()
    _effective_limit = qs._limit if qs._limit is not None else max_query_rows()
    if _effective_limit is not None:
        stmt = stmt.limit(_effective_limit)
    if qs._offset is not None:
        stmt = stmt.offset(qs._offset)

    async with connect(qs._db_alias, model_cls) as conn:
        try:
            result = await conn.execute(stmt)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            raise
        return [dict(row) for row in result.mappings()]


async def execute_aggregate(qs: QuerySet, agg_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute aggregate functions and return a single-row result dict.

    *agg_kwargs* maps alias names to _Aggregate instances.
    """
    model_cls = qs._model
    table = get_table(model_cls)

    agg_cols: list[Any] = []
    for alias, expr in agg_kwargs.items():
        sa_expr = ann_expr_as_sa(table, expr)
        if sa_expr is not None:
            agg_cols.append(sa_expr.label(alias))

    if not agg_cols:
        return {}

    stmt = sa.select(*agg_cols)

    q_filters = getattr(qs, "_q_filters", [])
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
    if where is not None:
        stmt = stmt.where(where)

    async with connect(qs._db_alias, model_cls) as conn:
        try:
            result = await conn.execute(stmt)
        except Exception as e:
            check_table_missing(e, model_cls)
            check_field_missing(e, model_cls)
            raise
        row = result.mappings().first()
        return dict(row) if row else {}


async def execute_explain(qs: QuerySet) -> str:
    """Return the database EXPLAIN output for the current query as a string.

    .. warning::

        EXPLAIN output may contain filter values from the query.  Never expose
        this output to untrusted users or log it in production environments
        where sensitive data (emails, passwords, PII) could appear in filter
        clauses.
    """
    model_cls = qs._model
    table = get_table(model_cls)
    stmt = sa.select(table)

    q_filters = getattr(qs, "_q_filters", [])
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
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

    async with connect(qs._db_alias, model_cls) as conn:
        if dialect_name == "postgresql":
            # PostgreSQL supports EXPLAIN as a prefix to SELECT.
            # Use parameterized compilation to avoid baking sensitive filter
            # values (emails, tokens, PII) into the SQL string.
            compiled = stmt.compile(
                dialect=_pg_dialect.dialect(),
                compile_kwargs={"literal_binds": False},
            )
            result = await conn.execute(sa.text(f"EXPLAIN {compiled}"))
            lines = [str(row[0]) for row in result]
        elif dialect_name == "sqlite":
            # SQLite EXPLAIN QUERY PLAN is a read-only introspection command.
            # Use parameterized compilation - placeholder values are shown as
            # bound parameters rather than raw literals.
            compiled = stmt.compile(compile_kwargs={"literal_binds": False})
            lines = [f"EXPLAIN QUERY PLAN {compiled}"]
        else:
            # Generic fallback - compile with parameter placeholders only.
            compiled = stmt.compile(compile_kwargs={"literal_binds": False})
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
        async with begin(model_class=model_cls) as conn:
            result = await conn.execute(upd_stmt, batch)
            total += result.rowcount

    if total:
        get_query_cache().invalidate_model(table.name)

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
    where = build_where_clause(table, qs._filters, qs._excludes, q_filters)
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

    async with connect(qs._db_alias, model_cls) as conn:
        result = await conn.stream(stmt)
        async for row in result.mappings().yield_per(chunk_size):
            yield dict(row)
