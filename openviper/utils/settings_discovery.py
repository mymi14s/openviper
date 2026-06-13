"""Settings auto-discovery for flexible project layouts.

Locates ``settings.py`` in the current working directory or within a
target module directory so that ``viperctl`` can set
``OPENVIPER_SETTINGS_MODULE`` without a pre-generated project scaffold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

TARGET_SEPARATORS: Final[frozenset[str]] = frozenset({"/", "\\"})


def discover_settings_module(
    target: str,
    cwd: Path | None = None,
    explicit: str | None = None,
) -> str | None:
    """Resolve a dotted settings module path.

    Resolution priority:

    1. *explicit* -- value from the ``--settings`` flag (returned as-is).
    2. Module settings -- ``<target>/settings.py`` exists inside *cwd*.
    3. Root settings -- ``settings.py`` directly in *cwd*.

    Args:
        target: The user-supplied target argument (``"."`` or a module name).
        cwd: Working directory to search from (defaults to ``Path.cwd()``).
        explicit: If the user passed ``--settings``, this is that value.

    Returns:
        Dotted Python module path (e.g. ``"todo.settings"`` or
        ``"settings"``), or ``None`` if no settings file was found.
    """
    if explicit is not None:
        return explicit

    cwd = cwd or Path.cwd()

    if target != ".":
        target_parts = target.split(".")
        if (
            not target_parts
            or any(separator in target for separator in TARGET_SEPARATORS)
            or any(not part.isidentifier() for part in target_parts)
        ):
            return None
        module_dir = cwd.joinpath(*target_parts)
        module_settings = module_dir / "settings.py"
        module_settings_package = module_dir / "settings" / "__init__.py"
        try:
            module_dir.resolve().relative_to(cwd.resolve())
        except ValueError:
            return None
        if module_settings.is_file():
            return f"{target}.settings"
        if module_settings_package.is_file():
            return f"{target}.settings"

    # Fall back to a root-level settings module at the project base.
    root_settings = cwd / "settings.py"
    if root_settings.is_file():
        return "settings"

    root_settings_package = cwd / "settings" / "__init__.py"
    if root_settings_package.is_file():
        return "settings"

    # When target is "." and no root settings exist, look for a single
    # package subdirectory containing settings.py.  This handles
    # module-organized projects where the CWD holds viperctl.py and a
    # package like "dayqurio/" with "dayqurio/settings.py".
    if target == ".":
        candidates: list[tuple[str, Path]] = []
        for child in sorted(cwd.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            if child.name in ("migrations", "static", "templates", "media", "logs", "tests"):
                continue
            if not (child / "__init__.py").is_file():
                continue
            if (child / "settings.py").is_file():
                candidates.append((child.name, child))
        if len(candidates) == 1:
            return f"{candidates[0][0]}.settings"

    return None
