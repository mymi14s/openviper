"""Migration writer — generates migration files from model introspection."""

from __future__ import annotations

import ast
import contextlib
import re
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from openviper.db.migrations.executor import Operation
    from openviper.db.models import Model
from openviper.db.fields import CheckConstraint, ForeignKey, UniqueConstraint
from openviper.db.migrations.executor import (
    AddColumn,
    AddConstraint,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    RemoveColumn,
    RemoveConstraint,
    RemoveIndex,
    RenameColumn,
    RestoreColumn,
    RunSQL,
    _types_compatible,
)
from openviper.exceptions import MigrationError

# Pattern for valid SQL/Python identifiers
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Column type substrings that require the PostGIS extension.
_POSTGIS_TYPE_MARKERS = ("GEOMETRY", "GEOGRAPHY", "RASTER", "TOPOGEOMETRY")


def _needs_postgis(model_classes: list[type[Any]]) -> bool:
    """Return True if any field in *model_classes* requires the PostGIS extension."""
    for model_cls in model_classes:
        for field in model_cls._fields.values():
            col_type = (field._column_type or "").upper()
            if any(marker in col_type for marker in _POSTGIS_TYPE_MARKERS):
                return True
    return False


def _needs_postgis_ops(operations: list[Any]) -> bool:
    """Return True if any CreateTable/AddColumn operation in *operations* uses a geometry type."""
    for op in operations:
        if isinstance(op, CreateTable):
            for col in op.columns:
                col_type = (col.get("type") or "").upper()
                if any(marker in col_type for marker in _POSTGIS_TYPE_MARKERS):
                    return True
        elif isinstance(op, AddColumn):
            col_type = (op.column_type or "").upper()
            if any(marker in col_type for marker in _POSTGIS_TYPE_MARKERS):
                return True
    return False


def _validate_identifier(name: str, context: str = "identifier") -> None:
    """Validate that a name is a safe SQL/Python identifier.

    Prevents code injection attacks where malicious model/table/column names
    could inject Python code into generated migration files.

    Args:
        name: The identifier to validate
        context: Description of what the identifier represents (for error messages)

    Raises:
        ValueError: If the identifier contains invalid characters
    """
    if not _IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {context}: {name!r}. "
            f"Identifiers must start with a letter or underscore, "
            f"followed by letters, digits, or underscores only."
        )


def _format_columns(model_cls: type[Model]) -> str:
    lines = []
    for _name, field in model_cls._fields.items():
        if field._column_type == "":
            continue

        # Validate column name to prevent code injection
        _validate_identifier(
            field.column_name, f"column name '{field.column_name}' in {model_cls.__name__}"
        )

        col: dict[str, Any] = {
            "name": field.column_name,
            "type": field._column_type,
            "nullable": field.null,
        }
        if field.primary_key:
            col["primary_key"] = True
        if field.auto_increment and field.primary_key:
            col["autoincrement"] = True
        if field.unique:
            col["unique"] = True
        if field.default is not None and not callable(field.default):
            col["default"] = field.default

        # Foreign Key support
        if isinstance(field, ForeignKey):
            target_model = field.resolve_target()
            if target_model:
                target_table = cast("Any", target_model)._table_name
                # Validate target table name
                _validate_identifier(target_table, f"target table name '{target_table}'")
                col["target_table"] = target_table
            elif isinstance(field.to, str):
                raise MigrationError(
                    f"Cannot serialize ForeignKey to '{field.to}': the target model could not be "
                    f"resolved. Ensure the target app is installed and the model is importable "
                    f"before generating migrations."
                )
            col["on_delete"] = field.on_delete

        lines.append(f"        {col!r},")
    return "\n".join(lines)


def _sort_models_topologically(model_classes: list[type[Model]]) -> list[type[Model]]:
    """Sort models based on ForeignKey dependencies within the same app."""
    # map table_name -> Model
    lookup = {m._table_name: m for m in model_classes}
    # build adjacency list and in-degree count
    adj: dict[str, Any] = {m._table_name: [] for m in model_classes}
    in_degree = {m._table_name: 0 for m in model_classes}

    for model_cls in model_classes:
        node = model_cls._table_name
        for field in model_cls._fields.values():
            if isinstance(field, ForeignKey):
                target = field.resolve_target()
                if (
                    target
                    and hasattr(target, "_table_name")
                    and target._table_name in lookup
                    and target._table_name != node
                ):
                    # Found intra-app dependency
                    adj[target._table_name].append(node)
                    in_degree[node] += 1

    # Initialize queue with zero in-degree nodes
    queue = deque([node for node, degree in in_degree.items() if degree == 0])
    sorted_nodes = []
    while queue:
        curr = queue.popleft()
        sorted_nodes.append(curr)
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If circular, append remaining to not lose data
    if len(sorted_nodes) < len(model_classes):
        remaining = [node for node in in_degree if node not in sorted_nodes]
        for node in remaining:
            sorted_nodes.append(node)

    return [lookup[node] for node in sorted_nodes]


def write_initial_migration(
    app_name: str,
    model_classes: list[type[Model]],
    migrations_dir: str,
    *,
    migration_name: str | None = None,
    dependencies: list[tuple[str, str]] | None = None,
) -> str:
    """Generate a migration file for the given models.

    Args:
        app_name: Name of the app (used in the file header).
        model_classes: List of Model subclasses to include.
        migrations_dir: Path to the ``<app>/migrations/`` directory.
        migration_name: Optional custom filename stem
            (e.g. ``"0002_add_email"``).  Defaults to ``"0001_initial"``.
        dependencies: Optional list of (app, migration_name) tuples.

    Returns:
        Path to the written migration file.
    """
    # Validate app_name to prevent code injection
    _validate_identifier(app_name, "app name")

    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    postgis_prefix = (
        '    migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS postgis;"),\n'
        if _needs_postgis(model_classes)
        else ""
    )

    tables_code = []
    # Sort models topologically to handle intra-app dependencies (e.g. Post before Comment)
    sorted_models = _sort_models_topologically(model_classes)
    for model_cls in sorted_models:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue

        # Validate table name to prevent code injection
        _validate_identifier(model_cls._table_name, f"table name for {model_cls.__name__}")

        cols = _format_columns(model_cls)
        block = f"""    migrations.CreateTable(
        table_name={model_cls._table_name!r},
        columns=[
{cols}
        ],
    ),"""
        tables_code.append(block)

    tables_str = "\n".join(tables_code)
    deps_str = repr(dependencies or [])
    # Extract any explicit CreateIndex operations from models
    extra_ops = []
    for model_cls in sorted_models:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue

        table_name = model_cls._table_name
        for idx in getattr(model_cls, "_meta_indexes", []):
            col_names = [
                model_cls._fields[f].column_name if f in model_cls._fields else f
                for f in idx.fields
            ]
            index_name = idx.name or f"idx_{table_name}_{'_'.join(col_names)}"
            extra_ops.append(
                f"    migrations.CreateIndex(\n"
                f"        table_name={table_name!r},\n"
                f"        index_name={index_name!r},\n"
                f"        columns={col_names!r},\n"
                f"    ),"
            )
        for _fname, field in model_cls._fields.items():
            if not field.db_index or field.unique or field.primary_key:
                continue
            col_name = field.column_name
            index_name = f"idx_{table_name}_{col_name}"
            extra_ops.append(
                f"    migrations.CreateIndex(\n"
                f"        table_name={table_name!r},\n"
                f"        index_name={index_name!r},\n"
                f"        columns=[{col_name!r}],\n"
                f"    ),"
            )
        for ut_fields in getattr(model_cls, "_meta_unique_together", []):
            col_names = [
                model_cls._fields[f].column_name if f in model_cls._fields else f for f in ut_fields
            ]
            index_name = f"uniq_{table_name}_{'_'.join(col_names)}"
            extra_ops.append(
                f"    migrations.CreateIndex(\n"
                f"        table_name={table_name!r},\n"
                f"        index_name={index_name!r},\n"
                f"        columns={col_names!r},\n"
                f"        unique=True,\n"
                f"    ),"
            )
        for constraint in getattr(model_cls, "_meta_constraints", []):
            if isinstance(constraint, CheckConstraint):
                extra_ops.append(
                    f"    migrations.AddConstraint(\n"
                    f"        table_name={table_name!r},\n"
                    f"        constraint_name={constraint.name!r},\n"
                    f"        constraint_type='CHECK',\n"
                    f"        check={constraint.check!r},\n"
                    f"    ),"
                )
            elif isinstance(constraint, UniqueConstraint):
                cond_part = (
                    f"\n        condition={constraint.condition!r}," if constraint.condition else ""
                )
                extra_ops.append(
                    f"    migrations.AddConstraint(\n"
                    f"        table_name={table_name!r},\n"
                    f"        constraint_name={constraint.name!r},\n"
                    f"        constraint_type='UNIQUE',\n"
                    f"        columns={constraint.fields!r},{cond_part}\n"
                    f"    ),"
                )

    if extra_ops:
        tables_str += "\n" + "\n".join(extra_ops)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    # Use repr() for app_name to prevent injection via f-string
    content = f'''"""Initial migration for {app_name!r}.

Auto-generated by OpenViper on {timestamp}.
"""

from openviper.db.migrations import executor as migrations

dependencies = {deps_str}

operations = [
{postgis_prefix}{tables_str}
]
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


def next_migration_number(migrations_dir: str) -> str:
    """Determine the next sequential migration number."""
    existing = [f.stem for f in Path(migrations_dir).glob("*.py") if not f.stem.startswith("_")]
    if not existing:
        return "0001"
    numbers = []
    for name in existing:
        with contextlib.suppress(ValueError):
            numbers.append(int(name.split("_")[0]))
    return str(max(numbers, default=0) + 1).zfill(4)


# ── Model state helpers ──────────────────────────────────────────────────


def model_state_snapshot(model_classes: list[type[Model]]) -> dict[str, dict[str, Any]]:
    """Build a deterministic snapshot of the current model state.

    Returns a dict mapping table names to complex state dicts:
    {
        "table_name": {
            "columns": [...],
            "indexes": [...],
            "unique_together": [...]
        }
    }
    """
    state: dict[str, dict[str, Any]] = {}
    for model_cls in model_classes:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
        cols: list[dict[str, Any]] = []
        for _name, field in model_cls._fields.items():
            if field._column_type == "":
                continue
            col: dict[str, Any] = {
                "name": field.column_name,
                "type": field._column_type,
                "field_class": type(field).__name__,
                "nullable": field.null,
            }
            if field.primary_key:
                col["primary_key"] = True
            if field.auto_increment and field.primary_key:
                col["autoincrement"] = True
            if field.unique:
                col["unique"] = True
            if field.default is not None and not callable(field.default):
                col["default"] = field.default
            cols.append(col)
        cols.sort(key=lambda c: c["name"])

        indexes = []
        for idx in getattr(model_cls, "_meta_indexes", []):
            col_names = [
                model_cls._fields[f].column_name if f in model_cls._fields else f
                for f in idx.fields
            ]
            index_name = idx.name or f"idx_{model_cls._table_name}_{'_'.join(col_names)}"
            indexes.append({"name": index_name, "fields": col_names})
        for _fname, field in model_cls._fields.items():
            if not field.db_index or field.unique or field.primary_key:
                continue
            col_name = field.column_name
            idx_name = f"idx_{model_cls._table_name}_{col_name}"
            indexes.append({"name": idx_name, "fields": [col_name]})
        indexes.sort(key=lambda x: x.get("name") or str(x.get("fields")))

        unique_together = [
            [model_cls._fields[f].column_name if f in model_cls._fields else f for f in ut]
            for ut in getattr(model_cls, "_meta_unique_together", [])
        ]
        unique_together.sort()

        state[model_cls._table_name] = {
            "columns": cols,
            "indexes": indexes,
            "unique_together": unique_together,
        }
    return state


def read_migrated_state(migrations_dir: str) -> dict[str, dict[str, Any]]:
    """Read all existing migration files and reconstruct the table state.

    Parses each migration's ``operations`` list to extract ``CreateTable``
    and ``CreateIndex`` calls to reconstruct the current database schema state.

    Returns the same structure as :func:`model_state_snapshot`.
    """
    # Reset soft-removed tracking for a clean parse
    _soft_removed_columns.clear()

    state: dict[str, dict[str, Any]] = {}
    mig_dir = Path(migrations_dir)
    if not mig_dir.is_dir():
        return state

    migration_files = sorted(f for f in mig_dir.glob("*.py") if not f.stem.startswith("_"))

    for mig_file in migration_files:
        source = mig_file.read_text()
        try:
            tree = ast.parse(source, filename=str(mig_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            if not any(t.id == "operations" for t in targets):
                continue
            if not isinstance(node.value, ast.List):
                continue
            for elt in node.value.elts:
                _parse_operation(elt, state)

    return state


def _get_op_name(node: ast.Call) -> str | None:
    """Return the operation class name from an AST Call node."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _get_keyword_str(node: ast.Call, key: str) -> str | None:
    """Extract a string keyword argument from an AST Call node."""
    for kw in node.keywords:
        if kw.arg == key and isinstance(kw.value, ast.Constant):
            return kw.value.value  # type: ignore[return-value]
    return None


def _parse_operation(node: ast.AST, state: dict[str, dict[str, Any]]) -> None:
    """Extract table info from a single AST operation node."""
    if not isinstance(node, ast.Call):
        return

    op_name = _get_op_name(node)
    if op_name is None:
        return

    if op_name == "CreateTable":
        _parse_create_table(node, state)
    elif op_name == "CreateIndex":
        _parse_create_index(node, state)
    elif op_name == "DropTable":
        table_name = _get_keyword_str(node, "table_name")
        if table_name:
            state.pop(table_name, None)
    elif op_name == "AddColumn":
        _parse_add_column(node, state)
    elif op_name == "RemoveColumn":
        _parse_remove_column(node, state)
    elif op_name == "AlterColumn":
        _parse_alter_column(node, state)
    elif op_name == "RemoveIndex":
        _parse_remove_index(node, state)
    elif op_name == "RenameColumn":
        _parse_rename_column(node, state)
    elif op_name == "RestoreColumn":
        _parse_restore_column(node, state)


def _parse_create_table(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a CreateTable operation."""
    table_name: str | None = None
    columns: list[dict[str, Any]] = []

    for kw in node.keywords:
        if kw.arg == "table_name" and isinstance(kw.value, ast.Constant):
            table_name = str(kw.value.value)
        elif kw.arg == "columns" and isinstance(kw.value, ast.List):
            for col_node in kw.value.elts:
                if isinstance(col_node, ast.Constant) and isinstance(col_node.value, dict):
                    columns.append(col_node.value)
                elif isinstance(col_node, ast.Dict):
                    col = _ast_dict_to_dict(col_node)
                    if col:
                        columns.append(col)

    if table_name is not None:
        columns.sort(key=lambda c: c.get("name", ""))
        state[table_name] = {
            "columns": columns,
            "indexes": [],
            "unique_together": [],
        }


def _parse_remove_index(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a RemoveIndex operation."""
    table_name = _get_keyword_str(node, "table_name")
    index_name = _get_keyword_str(node, "index_name")
    if not table_name or not index_name or table_name not in state:
        return
    state[table_name]["indexes"] = [
        idx for idx in state[table_name]["indexes"] if idx.get("name") != index_name
    ]
    state[table_name]["unique_together"] = [
        ut_fields
        for ut_fields in state[table_name]["unique_together"]
        if f"uniq_{table_name}_{'_'.join(ut_fields)}" != index_name
    ]
    state[table_name]["indexes"].sort(key=lambda x: x.get("name") or str(x.get("fields")))
    state[table_name]["unique_together"].sort()


def _parse_create_index(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a CreateIndex operation."""
    table_name = _get_keyword_str(node, "table_name")
    index_name = _get_keyword_str(node, "index_name")
    if not table_name:
        return

    columns: list[str] = []
    unique = False

    for kw in node.keywords:
        if kw.arg == "columns" and isinstance(kw.value, ast.List):
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant):
                    columns.append(str(elt.value))
        elif kw.arg == "unique" and isinstance(kw.value, ast.Constant):
            unique = bool(kw.value.value)

    if table_name not in state:
        state[table_name] = {"columns": [], "indexes": [], "unique_together": []}

    if unique:
        # If it's unique but doesn't have an autogenerated-looking name, it's unique_together
        if index_name and not index_name.startswith("uniq_"):
            state[table_name]["unique_together"].append(columns)
        else:
            state[table_name]["unique_together"].append(columns)
    else:
        state[table_name]["indexes"].append({"name": index_name, "fields": columns})

    # Keep sorted for deterministic diffs
    state[table_name]["indexes"].sort(key=lambda x: x.get("name") or str(x.get("fields")))
    state[table_name]["unique_together"].sort()


def _parse_add_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle an AddColumn operation."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    column_type = _get_keyword_str(node, "column_type")
    if not table_name or not column_name or not column_type:
        return

    # Determine nullable (default True in AddColumn)
    nullable = True
    default: Any = None
    for kw in node.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = bool(kw.value.value)
        elif kw.arg == "default" and isinstance(kw.value, ast.Constant):
            default = kw.value.value

    col: dict[str, Any] = {
        "name": column_name,
        "type": column_type,
        "nullable": nullable,
    }
    if default is not None:
        col["default"] = default

    if table_name not in state:
        state[table_name] = {"columns": [], "indexes": [], "unique_together": []}

    cols = state[table_name]["columns"]
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def _parse_remove_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a RemoveColumn operation."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    if not table_name or not column_name:
        return

    table_data = state.get(table_name, {"columns": [], "indexes": [], "unique_together": []})
    cols = table_data["columns"]
    # Find the column info before removing it, so we can track it
    removed_col = None
    for c in cols:
        if c.get("name") == column_name:
            removed_col = dict(c)
            break

    # Also check for column_type keyword in the operation itself
    column_type = _get_keyword_str(node, "column_type")

    if removed_col is None:
        removed_col = {"name": column_name, "type": column_type or "TEXT"}
    elif column_type:
        removed_col["type"] = column_type

    # Track this column as soft-removed
    _soft_removed_columns[(table_name, column_name)] = removed_col

    table_data["columns"] = [c for c in cols if c.get("name") != column_name]
    state[table_name] = table_data


def _parse_alter_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle an AlterColumn operation — update the column dict in state."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    if not table_name or not column_name:
        return

    table_data = state.get(table_name)
    if not table_data:
        return
    cols = table_data["columns"]
    for col in cols:
        if col.get("name") == column_name:
            # Update type if provided
            new_type = _get_keyword_str(node, "column_type")
            if new_type is not None:
                col["type"] = new_type
            # Update nullable if provided
            for kw in node.keywords:
                if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                    col["nullable"] = bool(kw.value.value)
                if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                    col["default"] = kw.value.value
            break


def _parse_rename_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a RenameColumn operation — update the column name in state."""
    table_name = _get_keyword_str(node, "table_name")
    old_name = _get_keyword_str(node, "old_name")
    new_name = _get_keyword_str(node, "new_name")
    if not table_name or not old_name or not new_name:
        return

    table_data = state.get(table_name)
    if not table_data:
        return
    cols = table_data["columns"]
    for col in cols:
        if col.get("name") == old_name:
            col["name"] = new_name
            break


def _parse_restore_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a RestoreColumn operation — re-add the column to state.

    The column was previously soft-removed (still in DB, tracked in
    ``openviper_soft_removed_columns``).  This adds it back to the
    migration state so the ORM recognizes it again.
    """
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    column_type = _get_keyword_str(node, "column_type")
    if not table_name or not column_name:
        return

    # Remove from soft-removed tracking
    key = (table_name, column_name)
    soft_info = _soft_removed_columns.pop(key, None)

    # Add column back to state
    col: dict[str, Any] = {
        "name": column_name,
        "type": column_type or (soft_info.get("type", "TEXT") if soft_info else "TEXT"),
        "nullable": True,  # Restored columns start as nullable
    }
    if table_name not in state:
        state[table_name] = {"columns": [], "indexes": [], "unique_together": []}

    cols = state[table_name]["columns"]
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def _ast_dict_to_dict(node: ast.Dict) -> dict[str, Any]:
    """Convert an ast.Dict of constants to a plain dict."""
    result: dict[str, Any] = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
            result[str(key.value)] = value.value
    return result


def has_model_changes(model_classes: list[type[Model]], migrations_dir: str) -> bool:
    """Return ``True`` if the models differ from what existing migrations cover."""
    current = model_state_snapshot(model_classes)
    existing = read_migrated_state(migrations_dir)
    return current != existing


# ── Diff-based migration generation ──────────────────────────────────────

# Global dict to track columns that have been soft-removed across migrations.
# Populated by read_migrated_state; maps (table_name, column_name) to col info.
_soft_removed_columns: dict[tuple[str, str], dict[str, Any]] = {}


def _check_was_soft_removed(
    column_name: str,
    table_name: str,
    existing: dict[str, dict[str, Any]],
    migrations_dir: str | None = None,
) -> dict[str, Any] | None:
    """Check if a column was previously soft-removed.

    Returns the column info dict if it was soft-removed, else None.
    """
    key = (table_name, column_name)
    if key in _soft_removed_columns:
        return _soft_removed_columns[key]
    return None


def _diff_states(
    current: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> list[Operation]:
    """Compare *current* model state with *existing* migrated state.

    Returns a list of :class:`Operation` objects that would bring the
    database from *existing* to *current*.
    """

    ops: list[Operation] = []

    # New tables
    new_table_names = sorted(current.keys() - existing.keys())
    if new_table_names:
        # Build dependency graph from snapshot column definitions
        adj: dict[str, Any] = {name: [] for name in new_table_names}
        in_degree = dict.fromkeys(new_table_names, 0)

        for name in new_table_names:
            cols = current[name]["columns"]
            for col in cols:
                target = col.get("target_table")
                if target and target in adj and target != name:
                    adj[target].append(name)
                    in_degree[name] += 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        sorted_new = []
        while queue:
            curr = queue.popleft()
            sorted_new.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Add remaining to avoid loss
        if len(sorted_new) < len(new_table_names):
            remaining = [n for n in new_table_names if n not in sorted_new]
            sorted_new.extend(remaining)

        for table_name in sorted_new:
            table_data = current[table_name]
            ops.append(CreateTable(table_name=table_name, columns=table_data["columns"]))

            # Add composite indexes for new tables
            for idx in table_data["indexes"]:
                index_name = idx.get("name") or f"idx_{table_name}_{'_'.join(idx['fields'])}"
                ops.append(
                    CreateIndex(table_name=table_name, index_name=index_name, columns=idx["fields"])
                )

            # Add unique constraints for new tables
            for ut_fields in table_data["unique_together"]:
                index_name = f"uniq_{table_name}_{'_'.join(ut_fields)}"
                ops.append(
                    CreateIndex(
                        table_name=table_name,
                        index_name=index_name,
                        columns=ut_fields,
                        unique=True,
                    )
                )

    # Dropped tables
    for table_name in sorted(existing.keys() - current.keys()):
        ops.append(DropTable(table_name=table_name))

    # Existing tables
    for table_name in sorted(current.keys() & existing.keys()):
        cur_data = current[table_name]
        old_data = existing[table_name]

        cur_cols = {c["name"]: c for c in cur_data["columns"]}
        old_cols = {c["name"]: c for c in old_data["columns"]}

        added_col_names = cur_cols.keys() - old_cols.keys()
        removed_col_names = old_cols.keys() - cur_cols.keys()

        restored: set[str] = set()
        restored_old_names: set[str] = set()

        # Handle restored/legacy column names
        for col_name in sorted(added_col_names):
            removed_name = f"_removed_{col_name}"
            if removed_name in old_cols:
                old_col = old_cols[removed_name]
                new_col = cur_cols[col_name]
                if not _types_compatible(old_col.get("type", "TEXT"), new_col.get("type", "TEXT")):
                    raise MigrationError(f"Incompatible types for restored column {col_name}")
                ops.append(
                    RenameColumn(table_name=table_name, old_name=removed_name, new_name=col_name)
                )
                restored.add(col_name)
                restored_old_names.add(removed_name)

        # Handle soft-removed restores
        for col_name in sorted(added_col_names - restored):
            was_soft = _check_was_soft_removed(col_name, table_name, existing)
            if was_soft:
                new_col = cur_cols[col_name]
                if not _types_compatible(was_soft.get("type", "TEXT"), new_col.get("type", "TEXT")):
                    raise MigrationError(f"Incompatible types for soft-restored column {col_name}")
                ops.append(
                    RestoreColumn(
                        table_name=table_name, column_name=col_name, column_type=new_col["type"]
                    )
                )
                # Warn about NOT NULL with potentially null data
                if not new_col.get("nullable", True):
                    print(
                        f"\n\033[93m"
                        f"WARNING: Restoring column '{col_name}' on table "
                        f"'{table_name}' as NOT NULL.\n"
                        f"  This column was previously soft-removed and may "
                        f"contain NULL values.\n"
                        f"  The migration will validate at runtime and fail if "
                        f"NULL rows exist.\n"
                        f"  Consider making the field nullable or providing a "
                        f"default value.\n"
                        f"\033[0m",
                        file=sys.stderr,
                    )
                    ops.append(
                        AlterColumn(
                            table_name=table_name,
                            column_name=col_name,
                            column_type=new_col["type"],
                            nullable=False,
                            old_nullable=True,
                        )
                    )
                restored.add(col_name)

        # Added columns
        for col_name in sorted(added_col_names - restored):
            col = cur_cols[col_name]
            ops.append(
                AddColumn(
                    table_name=table_name,
                    column_name=col["name"],
                    column_type=col["type"],
                    nullable=col.get("nullable", True),
                    default=col.get("default"),
                )
            )

        # Removed columns
        for col_name in sorted(removed_col_names - restored_old_names):
            old_col = old_cols[col_name]
            ops.append(
                RemoveColumn(
                    table_name=table_name,
                    column_name=col_name,
                    column_type=old_col.get("type", "TEXT"),
                )
            )

        # Altered columns
        for col_name in sorted(cur_cols.keys() & old_cols.keys()):
            cur = cur_cols[col_name]
            old = old_cols[col_name]
            type_changed = cur.get("type") != old.get("type")
            nullable_changed = cur.get("nullable") != old.get("nullable")
            default_changed = cur.get("default") != old.get("default")
            field_class_changed = (
                cur.get("field_class")
                and old.get("field_class")
                and cur.get("field_class") != old.get("field_class")
            )
            if type_changed or nullable_changed or default_changed or field_class_changed:
                ops.append(
                    AlterColumn(
                        table_name=table_name,
                        column_name=col_name,
                        column_type=cur.get("type"),
                        nullable=cur.get("nullable"),
                        default=cur.get("default"),
                        old_type=old.get("type"),
                        old_nullable=old.get("nullable"),
                        old_default=old.get("default"),
                    )
                )

        # Diff indexes
        cur_indexes = {
            (idx.get("name") or f"idx_{table_name}_{'_'.join(idx['fields'])}"): idx
            for idx in cur_data.get("indexes", [])
        }
        old_indexes = {
            (idx.get("name") or f"idx_{table_name}_{'_'.join(idx['fields'])}"): idx
            for idx in old_data.get("indexes", [])
        }

        for idx_name in sorted(cur_indexes.keys() - old_indexes.keys()):
            idx = cur_indexes[idx_name]
            ops.append(
                CreateIndex(table_name=table_name, index_name=idx_name, columns=idx["fields"])
            )

        for idx_name in sorted(old_indexes.keys() - cur_indexes.keys()):
            ops.append(RemoveIndex(table_name=table_name, index_name=idx_name))

        # Diff unique_together
        cur_ut = {tuple(fields) for fields in cur_data.get("unique_together", [])}
        old_ut = {tuple(fields) for fields in old_data.get("unique_together", [])}

        for fields in sorted(cur_ut - old_ut):
            index_name = f"uniq_{table_name}_{'_'.join(fields)}"
            ops.append(
                CreateIndex(
                    table_name=table_name, index_name=index_name, columns=list(fields), unique=True
                )
            )

        for fields in sorted(old_ut - cur_ut):
            index_name = f"uniq_{table_name}_{'_'.join(fields)}"
            ops.append(RemoveIndex(table_name=table_name, index_name=index_name))

    return ops


def _format_operation(op: Operation) -> str:
    """Render a single Operation as a string for a migration file."""

    if isinstance(op, CreateTable):
        col_lines = []
        for col in op.columns:
            col_lines.append(f"        {col!r},")
        cols_str = "\n".join(col_lines)
        return (
            f"    migrations.CreateTable(\n"
            f"        table_name={op.table_name!r},\n"
            f"        columns=[\n"
            f"{cols_str}\n"
            f"        ],\n"
            f"    ),"
        )
    if isinstance(op, DropTable):
        return f"    migrations.DropTable(table_name={op.table_name!r}),"
    if isinstance(op, CreateIndex):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        index_name={op.index_name!r}",
            f"        columns={op.columns!r}",
        ]
        if op.unique:
            parts.append(f"        unique={op.unique!r}")
        inner = ",\n".join(parts)
        return f"    migrations.CreateIndex(\n{inner},\n    ),"
    if isinstance(op, RemoveIndex):
        inner = f"table_name={op.table_name!r}, index_name={op.index_name!r}"
        return f"    migrations.RemoveIndex({inner}),"
    if isinstance(op, AddColumn):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        column_name={op.column_name!r}",
            f"        column_type={op.column_type!r}",
        ]
        if not op.nullable:
            parts.append(f"        nullable={op.nullable!r}")
        if op.default is not None:
            parts.append(f"        default={op.default!r}")
        inner = ",\n".join(parts)
        return f"    migrations.AddColumn(\n{inner},\n    ),"
    if isinstance(op, RemoveColumn):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        column_name={op.column_name!r}",
        ]
        if op.column_type != "TEXT":
            parts.append(f"        column_type={op.column_type!r}")
        if op.drop:
            parts.append(f"        drop={op.drop!r}")
        inner = ",\n".join(parts)
        return f"    migrations.RemoveColumn(\n{inner},\n    ),"
    if isinstance(op, AlterColumn):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        column_name={op.column_name!r}",
        ]
        if op.column_type is not None:
            parts.append(f"        column_type={op.column_type!r}")
        if op.nullable is not None:
            parts.append(f"        nullable={op.nullable!r}")
        if op.default is not None:
            parts.append(f"        default={op.default!r}")
        if op.old_type is not None:
            parts.append(f"        old_type={op.old_type!r}")
        if op.old_nullable is not None:
            parts.append(f"        old_nullable={op.old_nullable!r}")
        if op.old_default is not None:
            parts.append(f"        old_default={op.old_default!r}")
        inner = ",\n".join(parts)
        return f"    migrations.AlterColumn(\n{inner},\n    ),"
    if isinstance(op, RenameColumn):
        return (
            f"    migrations.RenameColumn(\n"
            f"        table_name={op.table_name!r},\n"
            f"        old_name={op.old_name!r},\n"
            f"        new_name={op.new_name!r},\n"
            f"    ),"
        )
    if isinstance(op, RestoreColumn):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        column_name={op.column_name!r}",
        ]
        if op.column_type != "TEXT":
            parts.append(f"        column_type={op.column_type!r}")
        inner = ",\n".join(parts)
        return f"    migrations.RestoreColumn(\n{inner},\n    ),"
    if isinstance(op, AddConstraint):
        parts = [
            f"        table_name={op.table_name!r}",
            f"        constraint_name={op.constraint_name!r}",
            f"        constraint_type={op.constraint_type!r}",
        ]
        if op.check:
            parts.append(f"        check={op.check!r}")
        if op.columns:
            parts.append(f"        columns={op.columns!r}")
        if op.condition:
            parts.append(f"        condition={op.condition!r}")
        inner = ",\n".join(parts)
        return f"    migrations.AddConstraint(\n{inner},\n    ),"
    if isinstance(op, RemoveConstraint):
        return (
            f"    migrations.RemoveConstraint(\n"
            f"        table_name={op.table_name!r},\n"
            f"        constraint_name={op.constraint_name!r},\n"
            f"        constraint_type={op.constraint_type!r},\n"
            f"    ),"
        )
    if isinstance(op, RunSQL):
        if op.reverse_sql:
            return f"    migrations.RunSQL(sql={op.sql!r}, reverse_sql={op.reverse_sql!r}),"
        return f"    migrations.RunSQL({op.sql!r}),"
    # Fallback for other ops
    return f"    # Unsupported operation: {op!r}"


def write_migration(
    app_name: str,
    operations: list[Operation],
    migrations_dir: str,
    *,
    migration_name: str | None = None,
    dependencies: list[tuple[str, str]] | None = None,
) -> str:
    """Generate a migration file containing the given *operations*.

    Unlike :func:`write_initial_migration`, this function accepts any
    list of :class:`Operation` objects — ``CreateTable``, ``AddColumn``,
    ``RemoveColumn``, ``DropTable``, etc.

    Args:
        app_name: Name of the app.
        operations: List of Operation objects.
        migrations_dir: Path to the migrations directory.
        migration_name: Optional custom filename stem.
        dependencies: List of (app, migration_name) dependencies.

    Returns:
        Path to the written migration file.
    """
    # Validate app_name to prevent code injection in generated migration
    _validate_identifier(app_name, "app name")

    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    if _needs_postgis_ops(operations):
        operations = [RunSQL("CREATE EXTENSION IF NOT EXISTS postgis;")] + list(operations)
    ops_str = "\n".join(_format_operation(op) for op in operations)
    deps_str = repr(dependencies or [])
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    content = f'''"""Migration for {app_name!r}.

Auto-generated by OpenViper on {timestamp}.
"""

from openviper.db.migrations import executor as migrations

dependencies = {deps_str}

operations = [
{ops_str}
]
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)
