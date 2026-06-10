"""OpenViper management command dispatcher.

Exposes :func:`execute_from_command_line` which is called by a project's
``viperctl.py`` to parse the command name from *argv* and dispatch to the
correct :class:`~openviper.core.management.base.BaseCommand` subclass.
"""

from __future__ import annotations

import functools
import importlib
import importlib.metadata
import logging
import os
import pkgutil
import sys
from pathlib import Path
from typing import NoReturn, cast

import openviper
from openviper.conf import settings
from openviper.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

_BUILTIN_COMMANDS_PACKAGE = "openviper.core.management.commands"


def extract_settings_flag(argv: list[str]) -> tuple[str | None, list[str]]:
    """Remove ``--settings=X`` / ``--settings X`` from *argv* and return its value.

    Returns:
        ``(settings_module, remaining_argv)`` where *settings_module* is ``None``
        if the flag was not present.
    """
    remaining: list[str] = []
    settings_value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--settings="):
            settings_value = arg[len("--settings=") :]
        elif arg == "--settings" and i + 1 < len(argv):
            i += 1
            settings_value = argv[i]
        else:
            remaining.append(arg)
        i += 1
    return settings_value, remaining


def auto_discover_settings(viperctl_path: str) -> str | None:
    """Attempt to discover a default settings module from the project layout.

    Discovery order (first match wins):

    Returns:
        Dotted settings module path, or ``None`` if nothing is found.
    """
    cwd = Path(viperctl_path).resolve().parent

    def _has_settings(item: Path) -> bool:
        """Return True when *item* is a package that ships a settings module.

        Supports both the single-file layout (``settings.py``) and the
        split-environment layout (``settings/__init__.py``).
        """
        if not (item.is_dir() and (item / "__init__.py").exists()):
            return False
        return (item / "settings.py").exists() or (item / "settings" / "__init__.py").exists()

    same_name = cwd / cwd.name
    if _has_settings(same_name):
        return f"{cwd.name}.settings"

    candidates = [item for item in cwd.iterdir() if _has_settings(item)]
    if len(candidates) == 1:
        return f"{candidates[0].name}.settings"

    if (cwd / "settings.py").exists():
        return "settings"

    return None


@functools.lru_cache(maxsize=32)
def find_command(name: str) -> BaseCommand:
    """Return a Command instance for *name*, searching built-ins then installed apps."""
    module_name = name.replace("-", "_")
    try:
        module = importlib.import_module(f"{_BUILTIN_COMMANDS_PACKAGE}.{module_name}")
        return cast("BaseCommand", module.Command())
    except ModuleNotFoundError:
        pass

    try:
        installed = getattr(settings, "INSTALLED_APPS", [])
    except Exception:
        logger.debug("Failed to read INSTALLED_APPS from settings", exc_info=True)
        installed = []

    for app in installed:
        try:
            module = importlib.import_module(f"{app}.management.commands.{module_name}")
            return cast("BaseCommand", module.Command())
        except ModuleNotFoundError:
            continue

    # Third-party plugins register commands via entry-points so they
    # auto-register without requiring INSTALLED_APPS entries.
    try:
        eps = importlib.metadata.entry_points(group="openviper.cli")
        for ep in eps:
            if ep.name == name:
                cmd_cls = ep.load()
                return cast("BaseCommand", cmd_cls())
    except Exception:
        logger.debug("No entry-point command found for %s", name, exc_info=True)
        pass

    raise CommandError(
        f"Unknown command: '{name}'.  Run 'viperctl.py help' for a list of commands.",
        returncode=1,
    )


@functools.lru_cache(maxsize=1)
def list_commands() -> list[str]:
    """Return sorted list of available built-in command names.

    Results are cached since available commands don't change at runtime.
    """
    pkg = importlib.import_module(_BUILTIN_COMMANDS_PACKAGE)
    pkg_path = pkg.__path__
    names = [
        name.replace("_", "-")
        for _finder, name, _ispkg in pkgutil.iter_modules(pkg_path)
        if not name.startswith("_")
    ]
    return sorted(names)


def execute_from_command_line(argv: list[str] | None = None) -> NoReturn:
    """Main entry point called from ``viperctl.py``.

    Supports a global ``--settings`` flag that overrides
    ``OPENVIPER_SETTINGS_MODULE`` for any subcommand::

        python viperctl.py --settings=project.settings.prod start-server
        python viperctl.py --settings=project.settings.dev migrate

    The flag is stripped from *argv* before passing to the subcommand so
    individual commands never see it.  The environment variable
    ``OPENVIPER_SETTINGS_MODULE`` takes effect first; ``--settings`` overrides
    it when both are present.

    If neither is supplied, the settings module is auto-discovered from the
    directory containing *viperctl.py* (looks for a sibling package that
    has a ``settings.py``).

    Usage::

        # viperctl.py
        #!/usr/bin/env python
        import sys
        from openviper.core.management import execute_from_command_line

        if __name__ == "__main__":
            execute_from_command_line(sys.argv)
    """
    argv = list(argv or sys.argv)

    settings_flag, argv = extract_settings_flag(argv)

    if settings_flag:
        os.environ["OPENVIPER_SETTINGS_MODULE"] = settings_flag

    discovered: str | None = None
    if not os.environ.get("OPENVIPER_SETTINGS_MODULE") and not settings_flag:
        discovered = auto_discover_settings(argv[0])
        if discovered:
            os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", discovered)

    # Force a reload when a settings module is known. Framework modules
    # (e.g. openviper.auth.jwt) access the settings proxy at import time,
    # pre-configuring the lazy proxy with the base Settings() class. If
    # OPENVIPER_SETTINGS_MODULE is in the environment, that premature load
    # may still produce the correct result, but silently falls back to
    # Settings() on import error or missing subclass. Forcing a reload
    # here guarantees the correct project settings are always used.
    openviper.setup(
        force=bool(settings_flag or discovered or os.environ.get("OPENVIPER_SETTINGS_MODULE"))
    )

    if len(argv) < 2 or argv[1] in ("help", "--help", "-h"):
        prog = os.path.basename(argv[0])
        print(f"Usage: {prog} [--settings=<module>] <command> [options]\n")
        print("  --settings   Dotted path to settings module, e.g. project.settings.prod\n")
        print("Available commands:")
        for cmd in list_commands():
            print(f"  {cmd}")
        sys.exit(0)

    subcommand = argv[1]

    try:
        command = find_command(subcommand)
    except CommandError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(exc.returncode)

    command.run_from_argv(argv)
    sys.exit(0)
