"""Flexible ``viperctl`` subcommand for ``openviper``.

Dispatches management commands (makemigrations, migrate, console, etc.)
across projects with non-standard layouts: root-level models,
standalone modules, or mixed arrangements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click

from openviper.core import flexible_adapter
from openviper.utils import module_resolver, settings_discovery

# Whitelist restricts dispatch to known-safe operations only.
ALLOWED_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "makemigrations",
        "migrate",
        "console",
        "start-server",
        "start-worker",
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
    """Dispatch a management *command* against *target*.

    Args:
        ctx: Click execution context.
        settings_module: Dotted path to settings module or ``None``.
        command: Management command name (e.g. ``makemigrations``).
        target: Relative module path or ``.`` for CWD-as-app.

    Raises:
        click.ClickException: Unknown command, invalid target, or
            dispatch failure.
    """
    if command not in ALLOWED_COMMANDS:
        valid = ", ".join(sorted(ALLOWED_COMMANDS))
        raise click.ClickException(f"Unknown command '{command}'. Valid commands: {valid}")

    # Prevent directory traversal in the target argument.
    if ".." in target or target.startswith("/"):
        raise click.ClickException(
            f"Invalid target '{target}'. Target must be a relative path without '..' components."
        )

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
    except click.ClickException:
        raise
    except ImportError as exc:
        raise click.ClickException(
            f"Module import failed: {exc.name!r}. Check that the module path is correct."
        ) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise click.ClickException(f"Command '{command}' failed: {exc}") from exc
