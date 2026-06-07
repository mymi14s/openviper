"""Target module resolver for flexible project layouts.

Translates the *target* argument (``"."`` or a module name) into a
concrete :class:`ResolvedModule` that the flexible adapter uses to
bootstrap the OpenViper environment.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Final

import click

TARGET_SEPARATORS: Final[frozenset[str]] = frozenset({"/", "\\"})


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
        return resolve_root(cwd)
    return resolve_module(target, cwd)


def resolve_root(cwd: Path) -> ResolvedModule:
    """Treat the CWD itself as the application module."""
    resolved_cwd = cwd.resolve()
    has_models = (resolved_cwd / "models.py").is_file()
    has_routes = (resolved_cwd / "routes.py").is_file()

    if not has_models and not has_routes:
        raise click.ClickException(
            f"Target '.' resolved to '{resolved_cwd}' but it contains "
            "neither models.py nor routes.py."
        )

    app_label = resolved_cwd.name
    if not app_label.isidentifier():
        raise click.ClickException(
            f"CWD directory name '{app_label}' is not a valid Python "
            "identifier. Rename the directory or use a module target instead."
        )

    return ResolvedModule(
        app_label=app_label,
        app_path=resolved_cwd,
        is_root=True,
        models_module=f"{app_label}.models",
    )


def resolve_module(target: str, cwd: Path) -> ResolvedModule:
    """Resolve a named module directory inside *cwd*."""
    target_parts = target.split(".")
    if (
        not target_parts
        or any(separator in target for separator in TARGET_SEPARATORS)
        or any(not part.isidentifier() for part in target_parts)
    ):
        raise click.ClickException(f"Target '{target}' is not a valid dotted Python module path.")

    app_path = cwd.joinpath(*target_parts)

    # Prevent path-traversal outside the project directory.
    try:
        app_path.resolve().relative_to(cwd.resolve())
    except ValueError:
        raise click.ClickException(
            f"Target '{target}' resolves outside the project directory."
        ) from None

    if not app_path.is_dir():
        raise click.ClickException(f"Target module '{target}' not found at '{app_path}'.")

    has_models = (app_path / "models.py").is_file()
    has_routes = (app_path / "routes.py").is_file()

    if not has_models and not has_routes:
        raise click.ClickException(
            f"Target '{target}' at '{app_path}' contains neither models.py nor routes.py."
        )

    return ResolvedModule(
        app_label=target,
        app_path=app_path,
        is_root=False,
        models_module=f"{target}.models",
    )
