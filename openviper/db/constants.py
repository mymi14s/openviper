"""Shared constants and helpers for the database package.

Centralises repeated ``getattr`` / ``hasattr`` patterns and module-level
constants so that a single source of truth is maintained across the ORM.
"""

from __future__ import annotations

import re
import typing as t
from typing import Final

UNSET: object = object()
"""Sentinel for "no value" used by migration operations and event hooks."""

SQLITE: str = "sqlite"
"""Dialect identifier for SQLite databases."""

POSTGRESQL: str = "postgresql"
"""Dialect identifier for PostgreSQL databases."""

MSSQL: str = "mssql"
"""Dialect identifier for Microsoft SQL Server databases."""

DEFAULT_ALIAS: str = "default"
"""Default database alias used when no explicit alias is specified."""

MIGRATION_TABLE_NAME: str = "openviper_migrations"
"""Table name for tracking applied migrations."""

SOFT_REMOVED_TABLE_NAME: str = "openviper_soft_removed_columns"
"""Table name for tracking soft-removed columns."""

PATCH_TABLE_NAME: str = "openviper_patches"
"""Table name for tracking applied data patches."""

DEFAULT_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "acronym",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "small",
        "strong",
        "sub",
        "sup",
        "ul",
    }
)
"""Default set of HTML tags allowed by HTMLField sanitisation."""

DEFAULT_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title"}),
}
"""Default attribute allowlist per HTML tag for HTMLField sanitisation."""

DEFAULT_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})
"""Default URL schemes permitted in href/src attributes."""

SUPPORTED_EVENTS: frozenset[str] = frozenset(
    {
        "before_validate",
        "validate",
        "before_insert",
        "before_save",
        "after_insert",
        "on_update",
        "on_change",
        "on_delete",
        "after_delete",
        "pre_bulk_create",
        "post_bulk_create",
        "pre_bulk_update",
        "post_bulk_update",
    }
)
"""Recognised model lifecycle event names."""


def get_model_fields(model_class: type) -> dict[str, t.Any]:
    """Return the ``_fields`` mapping from a model class.

    Consolidates the repeated ``getattr(model_class, "_fields", {})``
    pattern across the database module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The field name to field instance mapping.
    """
    return getattr(model_class, "_fields", {})


def get_model_meta(model_class: type) -> t.Any:
    """Return the ``_meta`` object from a model class, or ``None``.

    Consolidates the repeated ``getattr(model_class, "_meta", None)``
    pattern across the database module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The ``_meta`` namespace if present, otherwise ``None``.
    """
    return getattr(model_class, "_meta", None)


def get_app_label(model_class: type) -> str:
    """Return the app label for a model class.

    Checks ``_meta.app_label`` first, then falls back to the
    ``_app_name`` attribute, defaulting to ``"default"``.

    Args:
        model_class: The model class to inspect.

    Returns:
        The app label string.
    """
    meta = get_model_meta(model_class)
    if meta is not None:
        app_label = getattr(meta, "app_label", None)
        if isinstance(app_label, str):
            return app_label
    return getattr(model_class, "_app_name", "default")


# ---------------------------------------------------------------------------
# Engine / connection constants
# ---------------------------------------------------------------------------

COMPILED_CACHE_MAX_SIZE: Final[int] = 2048
"""Bounded LRU size for compiled query caches."""

# ---------------------------------------------------------------------------
# Executor - table/field safety and lookup operators
# ---------------------------------------------------------------------------

SAFE_TABLE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
"""Regex that matches safe SQL table identifiers."""

MAX_REGEX_LENGTH: Final[int] = 500
"""Cap regex length to mitigate ReDoS attack surface."""

# Nested quantifiers are the primary ReDoS vector.
REDoS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    \([^)]*[+*][^)]*\)\s*[+*]       # Nested quantifiers: (a+)+, (a*)*, etc.
    | \([^)]*\|[^)]*\)\s*[+*]       # Alternation with quantifier: (a|b)+
    | \(\?\:?\([^)]*[+*]            # Non-capturing nested: (?:(a+))
    | \(\?P?<[a-zA-Z]+>[^)]*[+*]    # Named group with quantifier: (?P<name>a+)
    """,
    re.VERBOSE,
)

# Reject regex operators that have no legitimate use in simple DB lookups
# and could enable ReDoS or DB-specific behavior exploitation.
UNSAFE_REGEX_CHARS: Final[frozenset[str]] = frozenset(
    {
        "\x00",  # Null byte injection.
        "\n",  # Newline injection.
        "\r",  # Carriage return injection.
        "\x1a",  # DB-specific sentinel characters.
    }
)

OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "exact",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "isnull",
        "range",
        "contains",
        "icontains",
        "startswith",
        "endswith",
        "iexact",
        "istartswith",
        "iendswith",
        "regex",
        "iregex",
    }
)
"""Supported ORM filter operators."""

DATETIME_TRANSFORMS: Final[frozenset[str]] = frozenset(
    {
        "date",
        "time",
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
    }
)
"""Date/time component transforms available as ORM lookup suffixes."""

# Redact common PII/credential field names from log output.
SENSITIVE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
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
"""Field names whose values are redacted in log output."""

TABLE_MISSING_RE: Final[re.Pattern[str]] = re.compile(
    r"no such table|relation.*doesn'?t exist|table.*does not exist|undefined table",
    re.IGNORECASE,
)
"""Matches DB error messages indicating a missing table."""

FIELD_MISSING_RE: Final[re.Pattern[str]] = re.compile(
    r"column[^\n]*does not exist|no such column|undefined column",
    re.IGNORECASE,
)
"""Matches DB error messages indicating an unknown column."""

FIELD_NAME_EXTRACT_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    (?:column\s+["']?([^"'\s().]+)["']?\s+does\s+not\s+exist)|  # PostgreSQL
    (?:no\s+such\s+column:\s+(?:\w+\.)?([^\s]+))|              # SQLite
    (?:Unknown\s+column\s+['"]([^'"]+)['"])|                   # MySQL
    (?:["']([^"'\s().]+)["']\s+does\s+not\s+exist)             # Alternative PostgreSQL
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""Extracts column names from DB missing-column error messages."""

AUTH_TABLE_PLURALIZATION: Final[dict[str, str]] = {
    "auth_role": "auth_roles",
    "auth_user": "auth_users",
    "auth_permission": "auth_permissions",
    "auth_contenttype": "auth_content_types",
    "auth_content_type": "auth_content_types",
}
"""Maps singular auth table names to their plural forms."""

TRAVERSAL_FAILURE: Final[object] = object()
"""Sentinel returned by the traversal cache to signal a failed lookup."""

# ---------------------------------------------------------------------------
# Utils - SQL safety patterns and on-delete actions
# ---------------------------------------------------------------------------

# SQL injection patterns for constraint names.
SQL_INJECTION_RE: Final[re.Pattern[str]] = re.compile(
    r";|--|/\*|\*/|(?i:\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE"
    r"|GRANT|REVOKE|EXEC(UTE)?|EXECUTE\s)\b)"
)
"""Matches SQL injection patterns in constraint/identifier names."""

VALID_ON_DELETE_ACTIONS: Final[frozenset[str]] = frozenset(
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
"""Permitted values for foreign-key ON DELETE actions."""

SAFE_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
"""Matches safe SQL identifiers (letters, digits, underscores)."""

# ---------------------------------------------------------------------------
# Migrations - dialect type mapping and DDL helpers
# ---------------------------------------------------------------------------

# Only types that differ across dialects need an entry.
DIALECT_TYPE_MAP: Final[dict[str, dict[str, str]]] = {
    "postgresql": {
        "DATETIME": "TIMESTAMP",
        "BINARY": "BYTEA",
        "TINYINT": "SMALLINT",
        "MEDIUMINT": "INTEGER",
        "DOUBLE": "DOUBLE PRECISION",
        "REAL": "DOUBLE PRECISION",
        "JSON": "JSONB",
        "UUID": "UUID",
    },
    "mysql": {
        "BINARY": "BLOB",
        "BOOLEAN": "TINYINT(1)",
        "UUID": "CHAR(36)",
        "REAL": "DOUBLE",
    },
    "sqlite": {
        "BOOLEAN": "INTEGER",
        "UUID": "TEXT",
        "JSON": "TEXT",
    },
    "mssql": {
        "BOOLEAN": "BIT",
        "UUID": "UNIQUEIDENTIFIER",
        "TEXT": "VARCHAR(MAX)",
        "JSON": "NVARCHAR(MAX)",
        "DATETIME": "DATETIME2",
    },
    "oracle": {
        "BOOLEAN": "NUMBER(1)",
        "TEXT": "CLOB",
        "JSON": "CLOB",
        "UUID": "VARCHAR2(36)",
        "VARCHAR": "VARCHAR2",
        "DATETIME": "TIMESTAMP",
        "INTEGER": "NUMBER",
        "BIGINT": "NUMBER",
    },
}
"""Per-dialect column type overrides for DDL generation."""

VARCHAR_TYPES: Final[frozenset[str]] = frozenset({"VARCHAR", "VARCHAR2"})
"""Column types that require an explicit length in certain dialects."""

VARCHAR_LENGTH_DIALECTS: Final[frozenset[str]] = frozenset({"mysql", "mssql", "oracle"})
"""Dialects that mandate a length for VARCHAR columns."""

PG_NEEDS_USING: Final[frozenset[str]] = frozenset(
    {
        "DOUBLE PRECISION",
        "REAL",
        "NUMERIC",
        "BIGINT",
        "INTEGER",
        "SMALLINT",
        "TEXT",
        "VARCHAR",
        "FLOAT",
    }
)
"""PostgreSQL types requiring a USING clause in ALTER COLUMN statements."""

BUILTIN_APP_PACKAGES: Final[list[str]] = [
    "openviper.admin",
    "openviper.auth",
    "openviper.tasks",
]
"""Built-in OpenViper apps that ship their own migrations."""

AUTH_USER_MODEL: Final[str] = "openviper.auth.models.User"
"""Default fully qualified path to the built-in User model."""

AUTH_USERS_TABLE: Final[str] = "auth_users"
"""Default database table name for the built-in User model."""

# ---------------------------------------------------------------------------
# Migrations writer - PostGIS detection
# ---------------------------------------------------------------------------

POSTGIS_RE: Final[re.Pattern[str]] = re.compile(
    r"geometry|geography|raster|topogeometry", flags=re.IGNORECASE
)
"""Matches PostGIS geometry/geography column types."""
