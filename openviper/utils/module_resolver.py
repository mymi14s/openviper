"""Target module resolver for flexible project layouts.

Translates the *target* argument (``"."`` or a module name) into a
concrete :class:`ResolvedModule` that the flexible adapter uses to
bootstrap the OpenViper environment.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import click


@dataclasses.dataclass(frozen=True, slots=True)
class ResolvedModule:
    """Result of resolving a ``viperctl`` target argument."""

    app_label: str
    """Importable app label, e.g. ``"todo"`` or the CWD directory name."""

    app_path: Path
    """Absolute filesystem path to the app directory."""

    is_root: bool
    """``True`` when the target was ``"."`` (CWD-as-app)."""

    models_module: str
    """Dotted import path for the models file, e.g. ``"todo.models"``."""


def resolve_target(
    target: str,
    cwd: Path | None = None,
) -> ResolvedModule:
    """Resolve a ``viperctl`` target string to a concrete module location.

    Args:
        target: ``"."`` for CWD-as-app, or a module name like ``"todo"``.
        cwd: Working directory (defaults to ``Path.cwd()``).

    Returns:
        A :class:`ResolvedModule` describing the target.

    Raises:
        click.ClickException: If the target cannot be resolved to a
            directory containing ``models.py`` or ``routes.py``.
    """
    cwd = cwd or Path.cwd()

    if target == ".":
        return _resolve_root(cwd)
    return _resolve_module(target, cwd)


def _resolve_root(cwd: Path) -> ResolvedModule:
    """Treat the CWD itself as the application module."""
    has_models = (cwd / "models.py").is_file()
    has_routes = (cwd / "routes.py").is_file()

    if not has_models and not has_routes:
        raise click.ClickException(
            f"Target '.' resolved to '{cwd}' but it contains neither " "models.py nor routes.py."
        )

    app_label = cwd.name
    if not app_label.isidentifier():
        raise click.ClickException(
            f"CWD directory name '{app_label}' is not a valid Python "
            "identifier. Rename the directory or use a module target instead."
        )

    return ResolvedModule(
        app_label=app_label,
        app_path=cwd,
        is_root=True,
        models_module=f"{app_label}.models",
    )


def _resolve_module(target: str, cwd: Path) -> ResolvedModule:
    """Resolve a named module directory inside *cwd*."""
    app_path = cwd / target

    if not app_path.is_dir():
        raise click.ClickException(f"Target module '{target}' not found at '{app_path}'.")

    has_models = (app_path / "models.py").is_file()
    has_routes = (app_path / "routes.py").is_file()

    if not has_models and not has_routes:
        raise click.ClickException(
            f"Target '{target}' at '{app_path}' contains neither " "models.py nor routes.py."
        )

    return ResolvedModule(
        app_label=target,
        app_path=app_path,
        is_root=False,
        models_module=f"{target}.models",
    )
