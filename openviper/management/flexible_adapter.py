"""Flexible adapter bridging ``viperctl`` to existing management commands.

Handles environment bootstrapping for non-standard project layouts:
setting up ``sys.path``, discovering/applying settings, injecting the
target app into ``INSTALLED_APPS``, and delegating to the standard
:func:`~openviper.core.management.execute_from_command_line` dispatcher.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click

if TYPE_CHECKING:
    from openviper.utils.module_resolver import ResolvedModule

logger = logging.getLogger("openviper.management.flexible_adapter")


def bootstrap_and_run(
    *,
    resolved: ResolvedModule,
    settings_module: str | None,
    command: str,
    command_args: tuple[str, ...],
) -> NoReturn:
    """Bootstrap the OpenViper environment and run a management command.

    1. Ensures the correct directories are on ``sys.path``.
    2. For root layouts, ensures ``__init__.py`` exists and sets the
       working directory to the app's parent so that
       :class:`~openviper.core.app_resolver.AppResolver` can locate
       the app as a subdirectory.
    3. Sets ``OPENVIPER_SETTINGS_MODULE`` (or synthesises a minimal
       in-memory settings module when none was discovered).
    4. Calls ``openviper.setup(force=True)`` to load settings.
    5. Injects the target app into ``INSTALLED_APPS`` if absent.
    6. Force-imports the target's ``models`` module so that model
       registrations happen before any command runs.
    7. Constructs a synthetic ``argv`` and calls
       :func:`~openviper.core.management.execute_from_command_line`.

    Args:
        resolved: The resolved target module info.
        settings_module: Dotted settings module path, or ``None``.
        command: Management command name (e.g. ``"makemigrations"``).
        command_args: Extra arguments to pass through to the command.
    """
    cwd = Path.cwd()

    if resolved.is_root:
        _prepare_root_layout(cwd)
    else:
        _ensure_sys_path(cwd)

    if settings_module is None:
        settings_module = _synthesize_settings_module()
        click.echo(
            "Warning: No settings.py found; using default settings.",
            err=True,
        )

    # For root layouts the settings module lives inside the app package.
    # Rewrite bare "settings" to "<app_label>.settings" so the importer
    # finds it via the parent directory that is now on sys.path.
    if resolved.is_root and settings_module == "settings":
        settings_module = f"{resolved.app_label}.settings"

    os.environ["OPENVIPER_SETTINGS_MODULE"] = settings_module

    import openviper

    openviper.setup(force=True)

    _inject_app_into_settings(resolved.app_label)
    _ensure_models_imported(resolved)

    # Build synthetic argv for the management command dispatcher.
    argv = ["viperctl", command, *command_args]

    from openviper.core.management import execute_from_command_line

    execute_from_command_line(argv)

    # execute_from_command_line calls sys.exit; this line is unreachable
    # but satisfies NoReturn.
    sys.exit(0)  # pragma: no cover


def _ensure_sys_path(path: Path) -> None:
    """Prepend *path* to ``sys.path`` if not already present."""
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _prepare_root_layout(cwd: Path) -> None:
    """Set up the environment for a root-layout project.

    :class:`~openviper.core.app_resolver.AppResolver` resolves apps by
    looking for subdirectories of the *project root* (``os.getcwd()``).
    In a root layout the CWD **is** the app, so AppResolver would search
    for ``<cwd>/<app_label>/`` which doesn't exist.

    This function:

    1. Ensures ``__init__.py`` exists in *cwd* so AppResolver considers
       it a valid app directory.
    2. Puts *cwd*'s **parent** on ``sys.path`` so that
       ``import <app_label>`` resolves to *cwd*.
    3. Changes the working directory to the parent so that
       ``AppResolver(project_root=os.getcwd())`` sees *cwd* as a child.
    """
    # 1. Ensure __init__.py so _is_valid_app_directory() passes.
    init_py = cwd / "__init__.py"
    if not init_py.exists():
        init_py.touch()
        logger.debug("Created %s for root layout", init_py)

    # 2. Parent on sys.path → ``import <cwd.name>`` works.
    _ensure_sys_path(cwd.parent)

    # 3. chdir so AppResolver's project_root becomes the parent.
    os.chdir(cwd.parent)
    logger.debug("Changed working directory to %s", cwd.parent)


def _inject_app_into_settings(app_label: str) -> None:
    """Add *app_label* to the live settings ``INSTALLED_APPS`` if absent.

    Uses :func:`dataclasses.replace` on the frozen ``Settings`` instance
    and replaces the ``_LazySettings._instance`` via
    ``object.__setattr__``.
    """
    from openviper.conf.settings import settings as _lazy

    current_apps: tuple[str, ...] = tuple(_lazy.INSTALLED_APPS)

    if app_label in current_apps:
        return

    instance = object.__getattribute__(_lazy, "_instance")
    if instance is None:  # pragma: no cover
        return

    new_instance = dataclasses.replace(
        instance,
        INSTALLED_APPS=(app_label, *current_apps),
    )
    object.__setattr__(_lazy, "_instance", new_instance)
    logger.debug("Injected '%s' into INSTALLED_APPS", app_label)


def _ensure_models_imported(resolved: ResolvedModule) -> None:
    """Force-import the target's models module.

    This triggers ``ModelMeta.__new__`` for all ``Model`` subclasses,
    ensuring they are in the global model registry before commands like
    ``makemigrations`` introspect it.

    For root layouts (bare ``models.py`` without ``__init__.py``), falls
    back to :func:`importlib.util.spec_from_file_location`.
    """
    try:
        importlib.import_module(resolved.models_module)
        return
    except ImportError:
        pass

    if not resolved.is_root:
        # For non-root layouts, the import should have worked.
        logger.debug(
            "Could not import '%s'; models may not be discovered.",
            resolved.models_module,
        )
        return

    # Root layout: models.py may be a bare file not inside a package.
    models_path = resolved.app_path / "models.py"
    if not models_path.is_file():
        return

    qualified_name = f"{resolved.app_label}.models"
    spec = importlib.util.spec_from_file_location(
        qualified_name,
        str(models_path),
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        return

    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = mod
    spec.loader.exec_module(mod)
    logger.debug(
        "Loaded root models from '%s' as '%s'",
        models_path,
        qualified_name,
    )


def _synthesize_settings_module() -> str:
    """Create and register a minimal in-memory settings module.

    Used when no ``settings.py`` was found anywhere.  Registers a module
    named ``_viperctl_settings`` in :data:`sys.modules` with a basic
    ``Settings`` subclass that uses SQLite defaults.

    Returns:
        The dotted name of the synthetic module.
    """
    from openviper.conf.settings import Settings

    @dataclasses.dataclass(frozen=True)
    class FlexibleSettings(Settings):
        PROJECT_NAME: str = "viperctl-project"
        DEBUG: bool = True
        DATABASE_URL: str = "sqlite+aiosqlite:///db.sqlite3"
        INSTALLED_APPS: tuple[str, ...] = ()

    module_name = "_viperctl_settings"
    mod = types.ModuleType(module_name)
    mod.__dict__["FlexibleSettings"] = FlexibleSettings
    sys.modules[module_name] = mod
    return module_name
