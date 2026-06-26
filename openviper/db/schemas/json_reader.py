"""Read JSON schema files and convert them to state dicts."""

from __future__ import annotations

import importlib
import logging
import typing as t
from pathlib import Path

import orjson

logger = logging.getLogger("openviper.schemas")


def read_json_schema(schemas_dir: str, model_name: str) -> dict[str, t.Any] | None:
    """Read a single JSON schema file.

    Args:
        schemas_dir: Path to the ``<app>/schemas/`` directory.
        model_name: Name of the model (file stem).

    Returns:
        Schema dict or None if the file does not exist.
    """
    path = Path(schemas_dir) / f"{model_name}.json"
    if not path.exists():
        return None
    return t.cast("dict[str, t.Any]", orjson.loads(path.read_bytes()))


def schema_to_state(schema: dict[str, t.Any]) -> dict[str, dict[str, t.Any]]:
    """Convert a single schema dict to the state dict format.

    The state dict maps table names to ``{"columns": [...], "indexes":
    [...], "unique_together": [...], "constraints": [...]}`` dicts,
    matching the output of ``model_state_snapshot``.

    Returns an empty dict if the model is marked as unmanaged.
    """
    table_name = schema["table_name"]
    if not schema.get("managed", True):
        return {}
    return {
        table_name: {
            "columns": list(schema.get("columns", [])),
            "indexes": list(schema.get("indexes", [])),
            "unique_together": list(schema.get("unique_together", [])),
            "index_together": list(schema.get("index_together", [])),
            "constraints": list(schema.get("constraints", [])),
        }
    }


def read_all_json_schemas(schemas_dir: str) -> dict[str, dict[str, t.Any]]:
    """Read all JSON schema files in a directory.

    Returns a state dict mapping table names to column/index data.
    """
    state: dict[str, dict[str, t.Any]] = {}
    schemas_path = Path(schemas_dir)
    if not schemas_path.is_dir():
        return state

    for json_file in sorted(schemas_path.glob("*.json")):
        schema = t.cast("dict[str, t.Any]", orjson.loads(json_file.read_bytes()))
        state.update(schema_to_state(schema))

    return state


def discover_json_schemas(
    resolved_apps: dict[str, str] | None = None,
) -> dict[str, dict[str, t.Any]]:
    """Discover and read all JSON schema files across installed apps.

    Scans both built-in OpenViper apps and project apps for ``schemas/``
    directories containing ``.json`` files.

    Args:
        resolved_apps: Dict of {app_name: app_path} from AppResolver.

    Returns:
        State dict mapping table names to schema data.
    """
    state: dict[str, dict[str, t.Any]] = {}

    builtin_apps = ("openviper.auth", "openviper.admin", "openviper.tasks")
    for dotted in builtin_apps:
        try:
            pkg = importlib.import_module(dotted)
        except Exception:
            logger.debug("Skipping unimportable built-in app: %s", dotted)
            continue
        pkg_file = getattr(pkg, "__file__", None)
        if pkg_file is None:
            continue
        pkg_dir = Path(pkg_file).resolve().parent
        schemas_dir = pkg_dir / "schemas"
        if schemas_dir.is_dir():
            state.update(read_all_json_schemas(str(schemas_dir)))

    if resolved_apps:
        for app_path in sorted(resolved_apps.values()):
            schemas_dir = Path(app_path) / "schemas"
            if schemas_dir.is_dir():
                state.update(read_all_json_schemas(str(schemas_dir)))

    return state


def list_schema_files(schemas_dir: str) -> list[str]:
    """Return sorted list of model names (file stems) in a schemas dir."""
    schemas_path = Path(schemas_dir)
    if not schemas_path.is_dir():
        return []
    return sorted(f.stem for f in schemas_path.glob("*.json"))


def read_all_raw_schemas(schemas_dir: str) -> dict[str, dict[str, t.Any]]:
    """Read all JSON schema files preserving the full schema dict.

    Returns a dict mapping table names to the full schema dict (including
    ``model``, ``app``, ``table_name`` keys).
    """
    result: dict[str, dict[str, t.Any]] = {}
    schemas_path = Path(schemas_dir)
    if not schemas_path.is_dir():
        return result
    for json_file in sorted(schemas_path.glob("*.json")):
        schema = t.cast("dict[str, t.Any]", orjson.loads(json_file.read_bytes()))
        table_name = schema.get("table_name", "")
        if table_name:
            result[table_name] = schema
    return result
