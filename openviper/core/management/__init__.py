"""OpenViper management command dispatcher.

Exposes :func:`execute_from_command_line` which is called by a project's
``viperctl.py`` to parse the command name from *argv* and dispatch to the
correct :class:`~openviper.core.management.base.BaseCommand` subclass.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import pkgutil
import sys
from typing import NoReturn

from openviper.conf import settings
from openviper.core.management.base import BaseCommand, CommandError

# ---------------------------------------------------------------------------
# Built-in command registry
# ---------------------------------------------------------------------------

_BUILTIN_COMMANDS_PACKAGE = "openviper.core.management.commands"


def _find_command(name: str) -> BaseCommand:
    """Return a Command instance for *name*, searching built-ins then installed apps."""
    module_name = name.replace("-", "_")
    # 1. Built-in commands
    try:
        module = importlib.import_module(f"{_BUILTIN_COMMANDS_PACKAGE}.{module_name}")
        return module.Command()  # type: ignore[attr-defined]
    except ModuleNotFoundError:
        pass

    # 2. Per-app management commands (e.g. myapp.management.commands.name)
    try:
        installed = getattr(settings, "INSTALLED_APPS", [])
    except Exception:
        installed = []

    for app in installed:
        try:
            module = importlib.import_module(f"{app}.management.commands.{module_name}")
            return module.Command()  # type: ignore[attr-defined]
        except ModuleNotFoundError:
            continue

    raise CommandError(
        f"Unknown command: '{name}'.  Run 'viperctl.py help' for a list of commands.",
        returncode=1,
    )


def _list_commands() -> list[str]:
    """Return sorted list of available built-in command names."""
    pkg = importlib.import_module(_BUILTIN_COMMANDS_PACKAGE)
    pkg_path = pkg.__path__  # type: ignore[attr-defined]
    names = [
        name.replace("_", "-")
        for _finder, name, _ispkg in pkgutil.iter_modules(pkg_path)
        if not name.startswith("_")
    ]
    return sorted(names)


def execute_from_command_line(argv: list[str] | None = None) -> NoReturn:
    """Main entry point called from ``viperctl.py``.

    Usage::

        # viperctl.py
        #!/usr/bin/env python
        import sys
        from openviper.core.management import execute_from_command_line

        if __name__ == "__main__":
            execute_from_command_line(sys.argv)
    """
    argv = argv or sys.argv

    # Explicitly trigger settings setup early to ensure OPENVIPER_SETTINGS_MODULE
    # is honored before any other framework objects (like models) are imported.
    with contextlib.suppress(Exception):
        # Accessing an attribute triggers _setup()
        _ = settings.DEBUG

    if len(argv) < 2 or argv[1] in ("help", "--help", "-h"):
        prog = os.path.basename(argv[0])
        print(f"Usage: {prog} <command> [options]\n")
        print("Available commands:")
        for cmd in _list_commands():
            print(f"  {cmd}")
        sys.exit(0)

    subcommand = argv[1]

    try:
        command = _find_command(subcommand)
    except CommandError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(exc.returncode)

    command.run_from_argv(argv)
    sys.exit(0)
