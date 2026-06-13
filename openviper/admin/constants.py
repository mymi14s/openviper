"""Shared constants and helpers for the admin package.

Centralises values that are referenced across multiple admin modules
so that a single source of truth is maintained.
"""

from __future__ import annotations

import json
import typing as t

from openviper.exceptions import NotFound

# --- Sensitive field name patterns -------------------------------------------

SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "secret",
        "key",
        "api_key",
        "access_token",
        "refresh_token",
    },
)
"""Field-name substrings that flag a field as sensitive.

Used by ``ModelAdmin.get_sensitive_fields`` and ``history`` masking
to ensure both modules apply the same policy.
"""

# --- Relational field type names --------------------------------------------

RELATIONAL_FIELD_TYPES: frozenset[str] = frozenset({"ForeignKey", "OneToOneField"})
"""Field class names that represent relational (FK / one-to-one) fields.

Referenced by ``options.py``, ``fields.py``, and ``views.py`` so that
adding a new relational field type only requires updating this set.
"""

# --- Admin access error message ----------------------------------------------

ADMIN_ACCESS_REQUIRED: str = "Admin access required."
"""Standard error message raised when a non-admin user attempts admin actions."""

# --- Minimum password length -------------------------------------------------

MIN_PASSWORD_LENGTH: int = 8
"""Minimum length enforced for admin password changes."""

MIN_PASSWORD_LENGTH_MSG: str = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
"""Pre-formatted message for password-length validation errors."""

PASSWORD_MISMATCH_MSG: str = "Passwords do not match."  # noqa: S105
"""Standard message for password confirmation mismatch."""

USER_NOT_FOUND_MSG: str = "User not found."
"""Standard message for user-not-found errors."""

# --- Access token expiry -----------------------------------------------------

ACCESS_TOKEN_EXPIRY_HOURS: int = 24
"""Number of hours until an access token expires."""

# --- Allowed admin SPA extension types ---------------------------------------

ALLOWED_EXTENSION_TYPES: frozenset[str] = frozenset({".js", ".vue"})
"""File extensions permitted for admin SPA extension serving."""

# --- Admin SPA not-built HTML ------------------------------------------------

ADMIN_NOT_BUILT_HTML: str = (
    "<h1>Admin Not Built</h1>"
    "<p>Run <code>cd admin_frontend && npm run build</code>"
    " to build the admin panel.</p>"
)
"""HTML body returned when the admin SPA has not been built yet."""

# --- Validation messages -----------------------------------------------------

NO_IDS_PROVIDED_MSG: str = "No IDs provided."
"""Standard message for bulk operations that received no IDs."""

ACTION_NAME_REQUIRED_MSG: str = "Action name is required."
"""Standard message for bulk actions missing an action name."""

BULK_ACTION_LIMIT: int = 1000
"""Maximum number of items allowed in a single bulk operation."""

BULK_ACTION_LIMIT_MSG: str = f"Cannot act on more than {BULK_ACTION_LIMIT} items at once."
"""Standard message for bulk-action limit violations."""

BULK_DELETE_LIMIT_MSG: str = f"Cannot delete more than {BULK_ACTION_LIMIT} items at once."
"""Standard message for bulk-delete limit violations."""

BULK_NOT_SUPPORTED_FOR_SINGLETON_MSG: str = (
    "Bulk actions are not supported for single-instance models."
)
"""Standard message when bulk actions are attempted on singleton models."""

EXPECTED_CHILD_ROWS_MSG: str = "Expected a list of row objects."
"""Standard message for invalid child-table row format."""

CHILD_ROW_MUST_BE_OBJECT_MSG: str = "Each child row must be an object."
"""Standard message for non-object child-table rows."""

CALLABLE_SENTINEL: str = "__callable__"
"""Sentinel value marking callable defaults that should be skipped during assignment."""

NON_FIELD_ERRORS_KEY: str = "__all__"
"""Dict key used for non-field-specific validation errors."""

INTEGRITY_CONFLICT_MSG: str = "A record with conflicting data already exists."
"""User-facing fallback for unique-constraint violations in production mode."""

INTEGRITY_CONFLICT_DEBUG_MSG: str = "A record with that data already exists."
"""User-facing message for unique-constraint violations when a duplicate is found."""

SINGLETON_MODEL_REQUIRED_MSG: str = "is not a singleton model."
"""Fragment used in singleton-model validation errors."""

SINGLETON_INSTANCE_NOT_FOUND_MSG: str = "instance not found."
"""Fragment used when a singleton model has no instance."""

SUPERUSER_PASSWORD_CHANGE_MSG: str = (
    "Only superusers can change other users' passwords."  # noqa: S105
)
"""Standard message for non-superuser password-change attempts."""

LOGGED_OUT_MSG: str = "Logged out successfully."
"""Standard message for successful logout responses."""

AUTH_REQUIRED_MSG: str = "Authentication required"
"""Standard message for unauthenticated admin access attempts."""

# --- BooleanField filter choices ---------------------------------------------

BOOLEAN_FIELD_CHOICES: list[dict[str, str]] = [
    {"value": "true", "label": "Yes"},
    {"value": "false", "label": "No"},
]
"""Standard filter choices for BooleanField, using string values for API consistency."""

# --- Numeric field type names ------------------------------------------------

NUMERIC_FIELD_TYPES: frozenset[str] = frozenset(
    {
        "IntegerField",
        "BigIntegerField",
        "PositiveIntegerField",
        "FloatField",
        "DecimalField",
    },
)
"""Field class names that represent numeric types for filter coercion."""

# --- Search field fallback names ---------------------------------------------

DEFAULT_SEARCH_FIELDS: list[str] = ["name", "title", "subject", "username", "email"]
"""Fallback field names used for global search when no search_fields are configured."""

# --- FK-search default limits ------------------------------------------------

FK_SEARCH_DEFAULT_LIMIT: int = 20
"""Default result limit for FK autocomplete search."""

FK_SEARCH_MAX_LIMIT: int = 100
"""Maximum result limit for FK autocomplete search."""

GLOBAL_SEARCH_PER_MODEL_LIMIT: int = 5
"""Maximum results per model in global search."""

GLOBAL_SEARCH_MAX_TOTAL: int = 50
"""Maximum total results across all models in global search."""

# --- Rate-limit defaults -----------------------------------------------------

RATE_LIMIT_AUTH: dict[str, int] = {"max_requests": 5, "window_seconds": 60}
"""Rate-limit parameters for authentication-sensitive endpoints."""

RATE_LIMIT_WRITE: dict[str, int] = {"max_requests": 10, "window_seconds": 60}
"""Rate-limit parameters for bulk write endpoints."""

RATE_LIMIT_EXPORT: dict[str, int] = {"max_requests": 5, "window_seconds": 60}
"""Rate-limit parameters for export endpoints."""

RATE_LIMIT_SEARCH: dict[str, int] = {"max_requests": 30, "window_seconds": 60}
"""Rate-limit parameters for search endpoints."""

# --- Export defaults ----------------------------------------------------------

ADMIN_MAX_EXPORT_ROWS: int = 10000
"""Default maximum rows for CSV/JSON export when settings.ADMIN_MAX_EXPORT_ROWS is unset."""

# --- CSV response headers ----------------------------------------------------

CSV_CONTENT_TYPE: str = "text/csv"
"""Content-Type header value for CSV responses."""

CSV_CONTENT_DISPOSITION: str = 'attachment; filename="{filename}.csv"'
"""Content-Disposition template for CSV export responses."""


# --- Helper functions --------------------------------------------------------


def is_admin_user(user: object) -> bool:
    """Return ``True`` if *user* has staff or superuser privileges.

    Safely handles objects that lack ``is_staff`` or ``is_superuser``
    attributes by falling back to ``False``.
    """
    return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)


def is_authenticated_admin(user: object | None) -> bool:
    """Return ``True`` if *user* is both authenticated and an admin.

    Combines the ``is_authenticated`` gate with :func:`is_admin_user`
    so callers do not need to repeat the two-step check.
    """
    if user is None:
        return False
    if not getattr(user, "is_authenticated", False):
        return False
    return is_admin_user(user)


def get_request_user(request: object) -> object | None:
    """Extract the authenticated user from a request, or ``None``.

    Returns ``None`` when the request has no ``user`` attribute or the
    user is not authenticated.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


def model_not_found(model_name: str, app_label: str | None = None) -> NotFound:
    """Return a ``NotFound`` exception for a missing model reference.

    Args:
        model_name: The model name that was not found.
        app_label: Optional app label for ``app_label/model_name`` format.
    """
    key = f"{app_label}/{model_name}" if app_label else model_name
    return NotFound(f"Model '{key}' not found.")


def default_related_name(child_model: type) -> str:
    """Derive the default reverse relation name for a child model.

    Follows the Django convention of ``<lowercase_model_name>_set``.
    """
    return child_model.__name__.lower() + "_set"


def detect_fk_name(child_model: type, parent_model: type) -> str | None:
    """Detect the FK field name linking *child_model* to *parent_model*.

    Scans ``child_model._fields`` for a ``ForeignKey`` or ``OneToOneField``
    whose target resolves to *parent_model*.
    """
    child_fields = get_model_fields(child_model)
    for name, field in child_fields.items():
        if (
            field.__class__.__name__ in RELATIONAL_FIELD_TYPES
            and field.resolve_target() == parent_model
        ):
            return name
    return None


def get_model_fields(model_class: type) -> dict[str, t.Any]:
    """Return the ``_fields`` mapping from a model class.

    Provides a safe fallback to an empty dict when the attribute is
    absent, consolidating the repeated ``getattr(model_class, "_fields", {})``
    pattern across the admin module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The field name to field instance mapping.
    """
    return getattr(model_class, "_fields", {})


def get_model_meta(model_class: type) -> t.Any:
    """Return the ``_meta`` object from a model class, or ``None``.

    Consolidates the repeated ``getattr(model_class, "_meta", None)``
    pattern across the admin module.

    Args:
        model_class: The model class to inspect.

    Returns:
        The ``_meta`` namespace if present, otherwise ``None``.
    """
    return getattr(model_class, "_meta", None)


def get_app_label(model_class: type) -> str:
    """Return the app label for a model class.

    Checks ``Meta.app_label`` first, then falls back to the
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
    if hasattr(model_class, "Meta") and hasattr(model_class.Meta, "app_label"):
        app_label = model_class.Meta.app_label
        if isinstance(app_label, str):
            return app_label
    return getattr(model_class, "_app_name", "default")


def instance_not_found(model_name: str, obj_id: str) -> NotFound:
    """Return a ``NotFound`` exception for a missing model instance.

    Args:
        model_name: The model name for the error message.
        obj_id: The instance ID that was not found.
    """
    return NotFound(f"{model_name} with id {obj_id} not found.")


def permission_denied_msg(action: str, target: str) -> str:
    """Return a standard permission-denied message.

    Args:
        action: The denied action verb (e.g. "view", "add", "change").
        target: The target model name.
    """
    return f"No permission to {action} {target}."


def serialize_user_dict(user: object) -> dict[str, object]:
    """Return a standardised dict representation of a user for API responses.

    Safely extracts common user attributes with fallback defaults.
    """
    return {
        "id": user.id,  # type: ignore[attr-defined]
        "username": user.username,  # type: ignore[attr-defined]
        "email": getattr(user, "email", ""),
        "is_staff": getattr(user, "is_staff", False),
        "is_superuser": getattr(user, "is_superuser", False),
    }


async def parse_request_data(request: t.Any) -> dict[str, t.Any]:
    """Parse request body as JSON or multipart form-data.

    For multipart requests, JSON-like string values (starting with
    ``[`` or ``{``) are deserialized automatically.
    """
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        data: dict[str, t.Any] = {}
        for k, v in form.items():
            if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                try:
                    data[k] = json.loads(v)
                except json.JSONDecodeError:
                    data[k] = v
            else:
                data[k] = v
        return data
    return await request.json()


def build_integrity_error_response(exc: t.Any, debug: bool, context: str = "") -> dict[str, t.Any]:
    """Build a standardised error payload for ``IntegrityError`` exceptions.

    In debug mode the original database message is exposed; in production
    the generic :data:`INTEGRITY_CONFLICT_MSG` is returned instead.

    Args:
        exc: The caught ``IntegrityError``.
        debug: Whether debug mode is active (``settings.DEBUG``).
        context: Optional label for log messages (e.g. ``"Create"``).
    """
    msg = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
    user_msg = msg if debug else INTEGRITY_CONFLICT_MSG
    return {"errors": {NON_FIELD_ERRORS_KEY: user_msg}}


def serialize_history_record(record: t.Any) -> dict[str, t.Any]:
    """Convert a ``ChangeHistory`` record into a JSON-safe dict.

    Args:
        record: A ``ChangeHistory`` model instance.
    """
    return {
        "id": record.id,
        "action": record.action,
        "changed_fields": record.get_changed_fields_dict(),
        "changed_by": record.changed_by_username,
        "change_time": (record.change_time.isoformat() if record.change_time else None),
        "message": record.change_message,
    }


def build_permission_denied_list_response(
    model_admin: t.Any, model_name: str, page: int, per_page: int
) -> dict[str, t.Any]:
    """Build the standard permission-denied response for list endpoints.

    Returns an empty result set with pagination metadata and a
    permission-denied flag so the frontend can display the reason.
    """
    return {
        "items": [],
        "total": 0,
        "page": page,
        "per_page": per_page,
        "total_pages": 0,
        "list_display": model_admin.get_list_display(None),
        "permission_denied": True,
        "permission_message": f"You do not have permission to view {model_name}.",
    }
