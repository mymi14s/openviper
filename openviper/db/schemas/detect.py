"""
Detect schema changes between model classes and JSON schema files.
Handles rename detection (matching by type), type change validation,
and identification of added/removed columns and tables.
"""

from __future__ import annotations

import typing as t

from openviper.db.fields import ForeignKey
from openviper.db.schema_builders import (
    build_model_constraints,
    build_model_index_together,
    build_model_indexes,
    build_model_unique_together,
)
from openviper.db.schemas.validate import validate_type_change
from openviper.utils import timezone

if t.TYPE_CHECKING:
    from openviper.db.models import Model


def match_renames(
    orphaned_json_cols: dict[str, dict[str, t.Any]],
    orphaned_model_cols: dict[str, dict[str, t.Any]],
) -> dict[str, str]:
    """Match removed JSON columns to new model columns by type.

    Returns a mapping of ``{new_col_name: old_col_name}`` for detected
    renames.  When multiple candidates share the same type, the first
    alphabetical match is chosen.
    """
    rename_map: dict[str, str] = {}
    used_old: set[str] = set()

    for new_name, new_col in sorted(orphaned_model_cols.items()):
        new_type = new_col.get("type", "")
        for old_name, old_col in sorted(orphaned_json_cols.items()):
            if old_name in used_old:
                continue
            old_type = old_col.get("type", "")
            if types_match(old_type, new_type):
                rename_map[new_name] = old_name
                used_old.add(old_name)
                break

    return rename_map


def types_match(old_type: str, new_type: str) -> bool:
    """Check if two column types are compatible for a rename."""
    old_base = old_type.upper().split("(")[0].strip()
    new_base = new_type.upper().split("(")[0].strip()
    return old_base == new_base


def detect_changes(
    model_classes: list[type[Model]],
    json_state: dict[str, dict[str, t.Any]],
    app_name: str,
    *,
    force: bool = False,
) -> dict[str, t.Any]:
    """Detect changes between model classes and existing JSON state.

    Args:
        model_classes: List of Model subclasses.
        json_state: State dict from reading existing JSON schema files.
        app_name: App label.

    Returns:
        Dict with keys:
            - ``created``: list of model classes needing new JSON files
            - ``updated``: list of (model_cls, changes) tuples
            - ``deleted``: list of model names whose JSON files should be removed
            - ``unchanged``: list of model names with no changes
    """
    model_table_names: dict[str, type[Model]] = {}
    for model_cls in model_classes:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
        model_opts = getattr(model_cls, "_meta", None)
        if model_opts is not None and model_opts.virtual:
            continue
        if not getattr(model_cls, "_is_managed", True):
            continue
        model_table_names[model_cls._table_name] = model_cls

    json_table_names = set(json_state.keys())
    model_table_set = set(model_table_names.keys())

    created: list[type[Model]] = []
    updated: list[tuple[type[Model], dict[str, t.Any]]] = []
    deleted: list[str] = []
    unchanged: list[str] = []

    for table_name, model_cls in model_table_names.items():
        if table_name not in json_table_names:
            created.append(model_cls)
            continue

        changes = detect_column_changes(model_cls, json_state[table_name], force=force)
        if changes:
            updated.append((model_cls, changes))
        else:
            unchanged.append(model_cls.__name__)

    for table_name in json_table_names - model_table_set:
        deleted.append(table_name)

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
    }


def detect_column_changes(
    model_cls: type[Model],
    json_table_state: dict[str, t.Any],
    *,
    force: bool = False,
) -> dict[str, t.Any]:
    """Detect column-level changes between a model and its JSON state.

    Returns an empty dict if no changes are detected.
    """
    model_cols: dict[str, dict[str, t.Any]] = {}
    for field in model_cls._fields.values():
        if field.column_type == "":
            continue
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
        if isinstance(field, ForeignKey):
            target_model = field.resolve_target()
            if target_model:
                col["target_table"] = t.cast("t.Any", target_model)._table_name
            col["on_delete"] = field.on_delete
        model_cols[field.column_name] = col

    json_cols = {c["name"]: c for c in json_table_state.get("columns", [])}

    model_col_names = set(model_cols.keys())
    json_col_names = set(json_cols.keys())

    orphaned_json = {n: c for n, c in json_cols.items() if n not in model_col_names}
    orphaned_model = {n: c for n, c in model_cols.items() if n not in json_col_names}

    rename_map = match_renames(orphaned_json, orphaned_model)

    changes: dict[str, t.Any] = {
        "added": [],
        "removed": [],
        "renamed": [],
        "altered": [],
    }

    for new_name, old_name in rename_map.items():
        changes["renamed"].append(
            {
                "new_name": new_name,
                "old_name": old_name,
                "column": model_cols[new_name],
            }
        )

    renamed_old_names = set(rename_map.values())
    renamed_new_names = set(rename_map.keys())

    for col_name in model_col_names - json_col_names - renamed_new_names:
        changes["added"].append(model_cols[col_name])

    for col_name in json_col_names - model_col_names - renamed_old_names:
        changes["removed"].append(json_cols[col_name])

    for col_name in model_col_names & json_col_names:
        model_col = model_cols[col_name]
        json_col = json_cols[col_name]

        type_changed = model_col.get("type") != json_col.get("type")
        nullable_changed = model_col.get("nullable") != json_col.get("nullable")
        default_changed = model_col.get("default") != json_col.get("default")
        unique_changed = model_col.get("unique") != json_col.get("unique")

        if type_changed:
            old_type = json_col.get("type", "")
            new_type = model_col.get("type", "")
            validate_type_change(old_type, new_type, force=force)

        if type_changed or nullable_changed or default_changed or unique_changed:
            changes["altered"].append(
                {
                    "name": col_name,
                    "old": json_col,
                    "new": model_col,
                }
            )

    model_indexes = {i["name"]: i for i in build_model_indexes(model_cls)}
    json_indexes = {i.get("name", ""): i for i in json_table_state.get("indexes", [])}
    if set(model_indexes.keys()) != set(json_indexes.keys()):
        changes["indexes_changed"] = True

    model_ut = {
        tuple(fields)
        for fields in build_model_unique_together(model_cls)
    }
    json_ut = {
        tuple(fields)
        for fields in json_table_state.get("unique_together", [])
    }
    if model_ut != json_ut:
        changes["unique_together_changed"] = True

    model_it = {
        tuple(fields)
        for fields in build_model_index_together(model_cls)
    }
    json_it = {
        tuple(fields)
        for fields in json_table_state.get("index_together", [])
    }
    if model_it != json_it:
        changes["index_together_changed"] = True

    model_constraints = build_model_constraints(model_cls)
    json_constraints = json_table_state.get("constraints", [])
    if model_constraints != json_constraints:
        changes["constraints_changed"] = True

    has_changes = any(changes.values())
    return changes if has_changes else {}


def apply_change_metadata(
    schema: dict[str, t.Any],
    changes: dict[str, t.Any],
) -> dict[str, t.Any]:
    """Apply transient change metadata to a schema dict.

    Adds ``old_name`` to renamed columns and ``old_type`` to altered
    columns so that ``migrate`` can issue the correct SQL.
    """
    now = timezone.now().isoformat()

    for rename in changes.get("renamed", []):
        for col in schema["columns"]:
            if col["name"] == rename["new_name"]:
                col["old_name"] = rename["old_name"]
                col["changed_at"] = now
                break

    for altered in changes.get("altered", []):
        for col in schema["columns"]:
            if col["name"] == altered["name"]:
                col["old_type"] = altered["old"].get("type")
                col["changed_at"] = now
                break

    return schema


def clean_change_metadata(schema: dict[str, t.Any]) -> dict[str, t.Any]:
    """Remove transient change metadata after successful migrate."""
    for col in schema.get("columns", []):
        col.pop("old_name", None)
        col.pop("old_type", None)
        col.pop("changed_at", None)
    return schema
