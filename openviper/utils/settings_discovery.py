"""Settings auto-discovery for flexible project layouts.

Locates ``settings.py`` in the current working directory or within a
target module directory so that ``viperctl`` can set
``OPENVIPER_SETTINGS_MODULE`` without a pre-generated project scaffold.
"""

from __future__ import annotations

from pathlib import Path


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

    # Module-level settings: <cwd>/<target>/settings.py
    if target != ".":
        module_settings = cwd / target / "settings.py"
        if module_settings.is_file():
            return f"{target}.settings"

    # Root-level settings: <cwd>/settings.py
    root_settings = cwd / "settings.py"
    if root_settings.is_file():
        return "settings"

    return None
