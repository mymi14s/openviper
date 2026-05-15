"""Flexible ``viperctl`` subcommand for ``openviper``.

Enables management commands (makemigrations, migrate, console, etc.) on
projects with non-standard layouts: root-level models, standalone
modules, or mixed arrangements.

Usage::

    openviper viperctl makemigrations .
    openviper viperctl migrate .
    openviper viperctl --settings todo.settings makemigrations todo
    openviper viperctl console
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click

from openviper.core import flexible_adapter
from openviper.utils import module_resolver, settings_discovery

# Supported management commands that can be dispatched through viperctl.
_ALLOWED_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "makemigrations",
        "migrate",
        "console",
        "startserver",
        "startworker",
        "collectstatic",
        "test",
        "createsuperuser",
        "changepassword",
    }
)


@click.command(
    "viperctl",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.option(
    "--settings",
    "settings_module",
    default=None,
    type=str,
    help="Dotted path to settings module (e.g. 'todo.settings' or 'settings').",
)
@click.argument("command", type=str)
@click.argument("target", default=".", type=str)
@click.pass_context
def viperctl(
    ctx: click.Context,
    settings_module: str | None,
    command: str,
    target: str,
) -> None:
    """Run management commands on flexible project layouts.

    \b
    COMMAND is one of the following management commands:
      makemigrations   Generate new database migration files.
      migrate          Apply pending database migrations.
      createsuperuser  Create a superuser account interactively.
      changepassword   Change a user's password.
      console            Open an interactive Python console with models loaded.
      startserver       Start the development web server.
      startworker        Start a background task worker.
      collectstatic    Collect static files into STATIC_ROOT.
      test             Run the project test suite via pytest.

    \b
    TARGET is '.' for CWD-as-app or a module name like 'todo' (default: '.').

    \b
    Examples:
      openviper viperctl makemigrations .
      openviper viperctl migrate .
      openviper viperctl --settings settings createsuperuser .
      openviper viperctl --settings settings changepassword .
      openviper viperctl console
    """
    if command not in _ALLOWED_COMMANDS:
        valid = ", ".join(sorted(_ALLOWED_COMMANDS))
        raise click.ClickException(f"Unknown command '{command}'. Valid commands: {valid}")

    cwd = Path.cwd()

    resolved = module_resolver.resolve_target(target, cwd=cwd)

    effective_settings = settings_discovery.discover_settings_module(
        target=target,
        cwd=cwd,
        explicit=settings_module,
    )

    extra_args = ctx.args

    try:
        flexible_adapter.bootstrap_and_run(
            resolved=resolved,
            settings_module=effective_settings,
            command=command,
            command_args=tuple(extra_args),
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
