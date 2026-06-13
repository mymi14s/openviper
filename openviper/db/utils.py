"""Database utilities for OpenViper ORM."""

from __future__ import annotations

import asyncio
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from openviper.db.exceptions import SingleModelAlreadyExistsError

if TYPE_CHECKING:
    from openviper.db.models import Model


def get_default_database_url(settings_obj: object) -> str:
    """Return the configured default database URL.

    Resolution order:
      1. ``DATABASES['default']['OPTIONS']['URL']`` (nested config format)
      2. ``DATABASES['default']['URL']`` (flat config format)
      3. ``DATABASE_URL`` (top-level legacy setting)
    """
    databases = getattr(settings_obj, "DATABASES", {})
    if isinstance(databases, Mapping):
        default_config = databases.get("default")
        if isinstance(default_config, Mapping):
            # New nested format: OPTIONS.URL
            options = default_config.get("OPTIONS")
            if isinstance(options, Mapping):
                url = options.get("URL")
                if isinstance(url, str) and url:
                    return url
            # Flat format: URL directly in default config
            url = default_config.get("URL")
            if isinstance(url, str) and url:
                return url

    # Legacy top-level DATABASE_URL fallback
    database_url = getattr(settings_obj, "DATABASE_URL", "")
    if isinstance(database_url, str) and database_url:
        return database_url
    return ""


def get_database_option(settings_obj: object, key: str, default: object = None) -> object:
    """Return a database option from DATABASES['default']['OPTIONS'].

    Falls back to a top-level ``DATABASE_<KEY>`` attribute for backward
    compatibility with the legacy flat-settings format.
    """
    databases = getattr(settings_obj, "DATABASES", {})
    if isinstance(databases, Mapping):
        default_config = databases.get("default")
        if isinstance(default_config, Mapping):
            options = default_config.get("OPTIONS")
            if isinstance(options, Mapping) and key in options:
                return options[key]
            if key in default_config:
                return default_config[key]
    # Legacy fallback: DATABASE_ECHO, DATABASE_POOL_SIZE, etc.
    legacy_key = f"DATABASE_{key}"
    legacy_val = getattr(settings_obj, legacy_key, None)
    if legacy_val is not None:
        return legacy_val
    return default


def get_database_routers(settings_obj: object) -> list[str]:
    """Return the configured database router import paths.

    Resolution order:
      1. ``DATABASES['ROUTERS']`` (nested config format)
      2. ``DATABASE_ROUTERS`` (top-level legacy setting)
    """
    databases = getattr(settings_obj, "DATABASES", {})
    if isinstance(databases, Mapping):
        routers = databases.get("ROUTERS")
        if isinstance(routers, list):
            return routers
    # Legacy fallback
    legacy = getattr(settings_obj, "DATABASE_ROUTERS", None)
    if isinstance(legacy, list):
        return legacy
    return []


async def enforce_single_model_constraint(model_cls: type[Model]) -> None:
    """Raise SingleModelAlreadyExistsError if a record already exists for a singleton model.

    Args:
        model_cls: The model class to check.
    """
    if await model_cls.objects.filter(ignore_permissions=True).exists():
        raise SingleModelAlreadyExistsError(f"{model_cls.__name__} allows only one logical record.")


class BoundedDict(OrderedDict):
    """OrderedDict subclass that evicts the oldest entries when exceeding *maxsize*.

    Used as the compiled-statement cache for SQLAlchemy so that workloads
    with many unique query patterns cannot cause unbounded memory growth.
    Eviction is O(1) per entry thanks to OrderedDict's popitem support.
    A threading lock guards mutations so the cache is safe for concurrent
    access from multiple threads sharing the same engine.
    """

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def __setitem__(self, key: object, value: object) -> None:
        with self._lock:
            if key in self:
                self.move_to_end(key)
                dict.__setitem__(self, key, value)
                return
            if len(self) >= self._maxsize:
                evict_count = max(1, self._maxsize // 4)
                for _ in range(evict_count):
                    self.popitem(last=False)
            dict.__setitem__(self, key, value)

    def __getitem__(self, key: object) -> object:
        with self._lock:
            return super().__getitem__(key)


# SQL injection patterns for constraint names.
_SQL_INJECTION_RE: Final[re.Pattern[str]] = re.compile(
    r";|--|/\*|\*/|(?i:\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE"
    r"|GRANT|REVOKE|EXEC(UTE)?|EXECUTE\s)\b)"
)

_VALID_ON_DELETE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "CASCADE",
        "PROTECT",
        "RESTRICT",
        "SET NULL",
        "SET DEFAULT",
        "NO ACTION",
        "SET_NULL",
        "SET_DEFAULT",
        "DO_NOTHING",
    }
)

_SAFE_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_sql_expression(value: str, field_name: str, context: str) -> str:
    """Reject SQL expressions containing destructive SQL patterns."""
    if _SQL_INJECTION_RE.search(value):
        raise ValueError(
            f"{context}.{field_name} contains disallowed SQL pattern: {value!r}. "
            f"Constraint expressions must not contain semicolons, SQL comments, "
            f"or DDL/DML keywords."
        )
    return value


def validate_identifier(name: str, description: str = "identifier") -> str:
    """Validate that *name* is a safe SQL identifier."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {description}: must contain only letters, digits, "
            f"and underscores, and must start with a letter or underscore."
        )
    return name


def validate_on_delete(action: str, context: str) -> str:
    """Validate that *action* is a supported ON DELETE action."""
    upper_action = action.upper()
    if upper_action not in _VALID_ON_DELETE_ACTIONS:
        raise ValueError(
            f"{context}: Invalid ON DELETE action '{action}'. "
            f"Valid actions: {', '.join(sorted(_VALID_ON_DELETE_ACTIONS))}"
        )
    return upper_action


def quote_identifier(name: str, dialect: str) -> str:
    """Quote a table or column name based on the database dialect."""
    if dialect == "mysql":
        return f"`{name.replace('`', '``')}`"
    if dialect == "mssql":
        return f"[{name.replace(']', ']]')}]"
    return f'"{name.replace(chr(34), chr(34) + chr(34))}"'


def sql_literal(value: object) -> str:
    """Format a Python value as a SQL literal.

    Uses the standard SQL escaping convention of doubling single quotes.
    Also escapes backslashes to prevent MySQL interpretation of ``\\``
    as an escape character within string literals.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


# Lazily creates one lock per running event loop.
#
# Sync fallback returns threading.Lock for non-async setup.

_per_loop_locks: dict[int, asyncio.Lock] = {}


def get_per_loop_lock(
    cache: dict[int, asyncio.Lock] | None = None,
) -> asyncio.Lock:
    """Return a lock scoped to the currently running event loop.

    When called from inside a running loop, returns an ``asyncio.Lock``
    scoped to that loop.  When no loop is running (e.g. during sync setup),
    creates a new event loop temporarily to construct an ``asyncio.Lock``
    that can later be awaited inside a real loop.  This prevents cross-loop
    state bleeding that would occur if an ``asyncio.Lock`` created outside
    any loop were later awaited inside one.

    Callers that use ``async with lock:`` must ensure they are inside a
    running event loop (i.e. within an ``async def``).

    Args:
        cache: Optional dict to use as the per-loop store.  When omitted,
            the module-level ``_per_loop_locks`` dict is used.
    """
    store = cache if cache is not None else _per_loop_locks
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if 0 not in store:
            store[0] = asyncio.Lock()
        return store[0]
    loop_id = id(loop)
    if loop_id not in store:
        store[loop_id] = asyncio.Lock()
    return store[loop_id]


def cleanup_stale_locks_for_cache(cache: dict[int, asyncio.Lock]) -> None:
    """Remove lock entries for event loops that are no longer running.

    Shared by ``connection.cleanup_stale_locks`` and
    ``DefaultDatabaseBackend.disconnect`` to avoid duplicating
    the stale-lock eviction logic.
    """
    stale_keys: list[int] = []
    for loop_id in list(cache):
        lock = cache[loop_id]
        if lock.locked():
            continue
        try:
            current_loop = asyncio.get_running_loop()
            if id(current_loop) == loop_id:
                continue
        except RuntimeError:
            pass
        stale_keys.append(loop_id)
    for key in stale_keys:
        cache.pop(key, None)


def cast_to_pk_type(model_class: type[Model], value: object) -> object:
    """Cast a value to the type of the model's primary key.

    Args:
        model_class: The model class to check.
        value: The value to cast.

    Returns:
        The value cast to the primary key's Python type.
    """
    if value is None:
        return None

    pk_field = next(
        (
            f
            for f in getattr(model_class, "_fields", {}).values()
            if getattr(f, "primary_key", False)
        ),
        None,
    )

    if pk_field and hasattr(pk_field, "to_python"):
        try:
            return pk_field.to_python(value)
        except ValueError, TypeError:
            return value

    return value
