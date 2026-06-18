"""Utility functions for management commands and CLI."""

from __future__ import annotations

import asyncio
import getpass
import inspect
from typing import Any

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand, CommandError
from openviper.db.models import Model
from openviper.db.utils import get_default_database_url


def get_banner(cmd_obj: BaseCommand | None, host: str, port: int) -> None:
    """Display the startup banner.

    Args:
        cmd_obj: Optional command object. Falls back to BaseCommand() when None.
        host: Server host.
        port: Server port.
    """
    if cmd_obj is None:
        cmd_obj = BaseCommand()

    banner = rf"""

            OOOOO  PPPPP   EEEEE  N   N  V   V  III  PPPPP  EEEEE  RRRR
           O     O P    P  E      NN  N  V   V   I   P    P E      R   R
           O     O PPPPP   EEEE   N N N  V   V   I   PPPPP  EEEE   RRRR
           O     O P       E      N  NN   V v    I   P      E      R  R
            OOOOO  P       EEEEE  N   N    V    III  P      EEEEE  R   R

            OpenViper development server running at http://{host}:{port}/
            Use Ctrl+C to stop.
            """
    cmd_obj.stdout(cmd_obj.style_success(banner))


def resolve_installed_apps(
    include_builtin: bool = False,
) -> tuple[AppResolver, dict[str, str]]:
    """Create an AppResolver, resolve INSTALLED_APPS, and return both.

    Returns:
        Tuple of (resolver, resolved_apps_dict).
    """
    resolver = AppResolver()
    installed_apps = getattr(settings, "INSTALLED_APPS", [])
    resolved = resolver.resolve_all_apps(installed_apps, include_builtin=include_builtin)
    resolved_apps = resolved.get("found", {})
    if not isinstance(resolved_apps, dict):
        resolved_apps = {}
    return resolver, resolved_apps


APP_NOT_FOUND_SEARCH_PATHS = ["{name}/", "apps/{name}/", "src/{name}/"]


def report_app_not_found(cmd: BaseCommand, app_label: str) -> None:
    """Print a consistent error message and hint for a missing app label."""
    cmd.stdout(
        cmd.style_error(
            f"\nError: App '{app_label}' not found in project or settings.INSTALLED_APPS\n"
        )
    )
    AppResolver.print_app_not_found_error(
        app_label,
        [path.format(name=app_label) for path in APP_NOT_FOUND_SEARCH_PATHS],
    )


def resolve_db_url(options: dict[str, Any]) -> str:
    """Resolve a database URL from command options or fall back to settings.

    Raises:
        CommandError: When no database URL is configured.
    """
    db_url: str | None = options.get("db")
    if not db_url:
        db_url = get_default_database_url(settings)
    if not db_url:
        raise CommandError("No default DATABASES URL configured. Use --db to specify one.")
    return db_url


def prompt_password(
    cmd: BaseCommand,
    prompt: str = "Password: ",
    confirm_prompt: str = "Password (again): ",
) -> str:
    """Interactively prompt for and confirm a password.

    Loops until the user provides a non-blank password that matches
    the confirmation prompt.

    Args:
        cmd: The management command instance (used for styled output).
        prompt: The initial password prompt text.
        confirm_prompt: The confirmation prompt text.

    Returns:
        The confirmed password string.

    Raises:
        CommandError: When the user cancels via KeyboardInterrupt or EOFError.
    """
    try:
        while True:
            password = getpass.getpass(prompt)
            if not password:
                cmd.stderr(cmd.style_error("Password cannot be blank."))
                continue
            confirm = getpass.getpass(confirm_prompt)
            if password != confirm:
                cmd.stderr(cmd.style_error("Passwords do not match. Try again."))
                continue
            return password
    except (EOFError, KeyboardInterrupt):
        cmd.stdout("\nOperation cancelled.")
        raise CommandError("Operation cancelled.") from None


def model_field_names(user_model: type) -> set[str]:
    """Return declared field names for *user_model*.

    Falls back to the built-in auth contract when model metadata
    is unavailable, which keeps command tests and simple mock
    models working.
    """
    fields = getattr(user_model, "_fields", None)
    if isinstance(fields, dict) and fields:
        return set(fields)
    return {"username", "email", "is_superuser", "is_staff", "is_active"}


def validate_identifier(name: str, label: str = "name") -> str:
    """Validate that *name* is a valid Python identifier.

    Args:
        name: The string to validate.
        label: Human-readable label for error messages (e.g. "command name").

    Returns:
        The validated name string.

    Raises:
        CommandError: When *name* is not a valid Python identifier.
    """
    if not name.isidentifier():
        raise CommandError(f"'{name}' is not a valid Python identifier.")
    return name


def discover_models_in_module(module: object) -> list[type]:
    """Return concrete Model subclasses defined in *module*.

    Skips abstract models and the base Model class itself.

    Args:
        module: The imported Python module to scan.

    Returns:
        A list of concrete Model subclasses found in the module.
    """
    models: list[type] = []
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        try:
            if (
                issubclass(obj, Model)
                and obj is not Model
                and obj.__module__ == getattr(module, "__name__", "")
            ):
                meta = getattr(obj, "Meta", None)
                if meta and getattr(meta, "abstract", False):
                    continue
                models.append(obj)
        except TypeError:
            continue
    return models


def run_async_command(coro: Any) -> Any:
    """Run an async coroutine from a sync management command.

    Handles the asyncio.run() + close() pattern and wraps
    unexpected exceptions in CommandError.

    Args:
        coro: The awaitable coroutine to run.

    Returns:
        The result of the coroutine.

    Raises:
        CommandError: When the coroutine raises a non-CommandError exception.
    """
    try:
        return asyncio.run(coro)
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError(str(exc)) from exc
    finally:
        coro.close()
