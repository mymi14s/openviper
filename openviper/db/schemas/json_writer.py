"""
Write, update, and delete JSON schema files for models.
Each model gets a single JSON file in ``<app>/schemas/<ModelName>.json``
that represents the desired database schema state.  The file is updated
in place when the model changes and deleted when the model is removed.
"""

from __future__ import annotations

import typing as t
from pathlib import Path

import orjson

from openviper.db.fields import ForeignKey
from openviper.db.schema_builders import (
    build_model_constraints,
    build_model_index_together,
    build_model_indexes,
    build_model_unique_together,
)
from openviper.db.utils import validate_identifier
from openviper.exceptions import MigrationError
from openviper.utils import timezone

if t.TYPE_CHECKING:
    from openviper.db.models import Model


def build_schema_dict(
    model_cls: type[Model],
    app_name: str,
) -> dict[str, t.Any]:
    """Build a serializable schema dict from a model class.

    Args:
        model_cls: Model subclass to introspect.
        app_name: App label the model belongs to.

    Returns:
        Dict suitable for JSON serialization, or None if the model is
        unmanaged and should be excluded from schema tracking.
    """
    if not getattr(model_cls, "_is_managed", True):
        return None

    validate_identifier(model_cls._table_name, f"table name for {model_cls.__name__}")

    columns: list[dict[str, t.Any]] = []
    for field in model_cls._fields.values():
        if field.column_type == "":
            continue

        validate_identifier(
            field.column_name,
            f"column name '{field.column_name}' in {model_cls.__name__}",
        )

        col: dict[str, t.Any] = {
            "name": field.column_name,
            "type": field.column_type,
            "nullable": field.null,
        }
        if field.primary_key:
            col["primary_key"] = True
        if field.auto_increment and field.primary_key:
            col["autoincrement"] = True
        if field.unique:
            col["unique"] = True
        col["default"] = field.default if not callable(field.default) else None

        if field.choices:
            col["choices"] = [
                {"value": c[0], "label": c[1]} for c in field.choices
            ]

        if isinstance(field, ForeignKey):
            target_model = field.resolve_target()
            if target_model:
                col["target_table"] = t.cast("t.Any", target_model)._table_name
            elif isinstance(field.to, str):
                raise MigrationError(
                    f"Cannot serialize ForeignKey to '{field.to}': the target "
                    f"model could not be resolved. Ensure the target app is "
                    f"installed and the model is importable before generating "
                    f"schemas."
                )
            col["on_delete"] = field.on_delete

        columns.append(col)

    columns.sort(key=lambda c: c["name"])

    indexes = build_model_indexes(model_cls)
    unique_together = build_model_unique_together(model_cls)
    index_together = build_model_index_together(model_cls)
    constraints = build_model_constraints(model_cls)

    return {
        "model": model_cls.__name__,
        "app": app_name,
        "table_name": model_cls._table_name,
        "last_modified": timezone.now().isoformat(),
        "columns": columns,
        "indexes": indexes,
        "unique_together": unique_together,
        "index_together": index_together,
        "constraints": constraints,
        "single": getattr(model_cls, "_is_single", False),
        "managed": getattr(model_cls, "_is_managed", True),
    }


def write_json_schema(
    schemas_dir: str,
    model_cls: type[Model],
    app_name: str,
    *,
    existing_schema: dict[str, t.Any] | None = None,
) -> str:
    """Write or update a JSON schema file for a model.

    Preserves transient change metadata (``old_name``, ``old_type``)
    from *existing_schema* when merging column definitions.

    Args:
        schemas_dir: Path to the ``<app>/schemas/`` directory.
        model_cls: Model subclass.
        app_name: App label.
        existing_schema: Previously loaded schema dict, used to carry
            forward rename and type-change metadata.

    Returns:
        Path to the written JSON file, or empty string if the model is
        unmanaged and should be skipped.
    """
    validate_identifier(app_name, "app name")

    new_schema = build_schema_dict(model_cls, app_name)

    if new_schema is None:
        return ""

    if existing_schema:
        old_cols = {c["name"]: c for c in existing_schema.get("columns", [])}
        for col in new_schema["columns"]:
            old_col = old_cols.get(col["name"])
            if old_col and old_col.get("old_name"):
                col["old_name"] = old_col["old_name"]
            if old_col and old_col.get("old_type"):
                col["old_type"] = old_col["old_type"]

    path = Path(schemas_dir) / f"{model_cls.__name__}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(new_schema, option=orjson.OPT_INDENT_2))
    return str(path)


def delete_json_schema(schemas_dir: str, model_name: str) -> bool:
    """Delete a JSON schema file for a model.

    Args:
        schemas_dir: Path to the ``<app>/schemas/`` directory.
        model_name: Name of the model (file stem).

    Returns:
        True if the file was deleted, False if it did not exist.
    """
    path = Path(schemas_dir) / f"{model_name}.json"
    if path.exists():
        path.unlink()
        return True
    return False
