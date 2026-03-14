"""Flexible ``viperctl`` subcommand for ``openviper``.

Enables management commands (makemigrations, migrate, shell, etc.) on
projects with non-standard layouts: root-level models, standalone
modules, or mixed arrangements.

Usage::

    openviper viperctl makemigrations .
    openviper viperctl migrate .
    openviper viperctl --settings todo.settings makemigrations todo
    openviper viperctl shell
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click

# Supported management commands that can be dispatched through viperctl.
_ALLOWED_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "makemigrations",
        "migrate",
        "shell",
        "runworker",
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
      shell            Open an interactive Python shell with models loaded.
      runworker        Start a background task worker.
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
      openviper viperctl shell
    """
    if command not in _ALLOWED_COMMANDS:
        valid = ", ".join(sorted(_ALLOWED_COMMANDS))
        raise click.ClickException(f"Unknown command '{command}'. Valid commands: {valid}")

    # Lazy imports -- only incur the cost when viperctl is actually invoked.
    from openviper.core.flexible_adapter import bootstrap_and_run
    from openviper.utils.module_resolver import resolve_target
    from openviper.utils.settings_discovery import discover_settings_module

    cwd = Path.cwd()

    resolved = resolve_target(target, cwd=cwd)

    effective_settings = discover_settings_module(
        target=target,
        cwd=cwd,
        explicit=settings_module,
    )

    # Extra args captured by Click's allow_extra_args.
    extra_args: tuple[str, ...] = tuple(ctx.args)

    bootstrap_and_run(
        resolved=resolved,
        settings_module=effective_settings,
        command=command,
        command_args=extra_args,
    )
