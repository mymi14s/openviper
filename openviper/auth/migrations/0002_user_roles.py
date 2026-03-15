"""Create auth_user_roles junction table.

This migration runs after both auth/0001_initial and the configured user
app's initial migration, since auth_user_roles holds a FK to the user table.
"""

from openviper.conf import settings as _openviper_settings
from openviper.db.migrations import executor as migrations

_AUTH_USER = "openviper.auth.models.User"


def _resolve_user_table() -> str:
    """Return the configured User model's DB table, falling back to auth_users."""
    user_model_path = getattr(_openviper_settings, "USER_MODEL", None) or getattr(
        _openviper_settings, "AUTH_USER_MODEL", None
    )
    if user_model_path and user_model_path != _AUTH_USER and "." in user_model_path:
        try:
            from importlib import import_module

            module_path, class_name = user_model_path.rsplit(".", 1)
            mod = import_module(module_path)
            cls = getattr(mod, class_name)
            meta = getattr(cls, "Meta", None)
            return getattr(meta, "table_name", "auth_users") if meta else "auth_users"
        except Exception:
            pass


def _resolve_user_dependency() -> list[tuple[str, str]]:
    """Return a dependency on the custom user app's first migration, if applicable."""
    user_model_path = getattr(_openviper_settings, "USER_MODEL", None) or getattr(
        _openviper_settings, "AUTH_USER_MODEL", None
    )
    if user_model_path and user_model_path != _AUTH_USER and "." in user_model_path:
        # Derive app name from the top-level package of the model path.
        # e.g. "users.models.User" -> "users"
        app_name = user_model_path.split(".")[0]
        return [(app_name, "0001_initial")]
    return []


_USER_TABLE = _resolve_user_table()

dependencies: list[tuple[str, str]] = [("auth", "0001_initial")] + _resolve_user_dependency()

operations = [
    migrations.CreateTable(
        table_name="auth_user_roles",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "nullable": False,
                "primary_key": True,
                "autoincrement": True,
            },
            {
                "name": "user_id",
                "type": "INTEGER",
                "nullable": False,
                "target_table": _USER_TABLE,
                "on_delete": "CASCADE",
            },
            {
                "name": "role_id",
                "type": "INTEGER",
                "nullable": False,
                "target_table": "auth_roles",
                "on_delete": "CASCADE",
            },
        ],
    ),
]
