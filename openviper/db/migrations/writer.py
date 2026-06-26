"""Migration writer - generates migration files from model introspection."""

from __future__ import annotations

import ast
import contextlib
import copy
import re
import sys
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from openviper.utils import timezone

if TYPE_CHECKING:
    from openviper.db.migrations.executor import Operation
    from openviper.db.models import Model

from openviper.db.constants import POSTGIS_RE, UNSET
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
    types_compatible,
)
from openviper.db.schema_builders import (
    build_model_constraints,
    build_model_index_together,
    build_model_indexes,
    build_model_unique_together,
)
from openviper.db.utils import validate_identifier
from openviper.exceptions import MigrationError


def needs_postgis(model_classes: list[type[Any]]) -> bool:
    """Return True if any field in *model_classes* requires the PostGIS extension."""
    for model_cls in model_classes:
        for field in model_cls._fields.values():
            if POSTGIS_RE.search(field.column_type or ""):
                return True
    return False


def needs_postgis_ops(operations: list[Any]) -> bool:
    """Return True if any CreateTable/AddColumn operation uses a PostGIS geometry type."""
    for op in operations:
        if isinstance(op, CreateTable):
            for col in op.columns:
                if POSTGIS_RE.search(col.get("type") or ""):
                    return True
        elif isinstance(op, AddColumn) and POSTGIS_RE.search(op.column_type or ""):
            return True
    return False


# ---------------------------------------------------------------------------
# Column / model formatting
# ---------------------------------------------------------------------------

def format_columns(model_cls: type[Model]) -> str:
    """Render all columns of *model_cls* as Python dict literals for a migration file."""
    lines: list[str] = []
    for _name, field in model_cls._fields.items():
        if field.column_type == "":
            continue

        validate_identifier(
            field.column_name,
            f"column name '{field.column_name}' in {model_cls.__name__}",
        )

        col: dict[str, Any] = {
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
        if field.default is not None and not callable(field.default):
            col["default"] = field.default

        if isinstance(field, ForeignKey):
            target_model = field.resolve_target()
            if target_model:
                target_table = cast("Any", target_model)._table_name
                validate_identifier(target_table, f"target table name '{target_table}'")
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


def sort_models_topologically(model_classes: list[type[Model]]) -> list[type[Model]]:
    """Sort models by intra-app ForeignKey dependencies using Kahn's algorithm."""
    lookup = {m._table_name: m for m in model_classes}
    adj: dict[str, list[str]] = {m._table_name: [] for m in model_classes}
    in_degree: dict[str, int] = dict.fromkeys(adj, 0)

    for model_cls in model_classes:
        node = model_cls._table_name
        for field in model_cls._fields.values():
            if not isinstance(field, ForeignKey):
                continue
            target = field.resolve_target()
            if (
                target
                and hasattr(target, "_table_name")
                and target._table_name in lookup
                and target._table_name != node
            ):
                adj[target._table_name].append(node)
                in_degree[node] += 1

    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    sorted_nodes: list[str] = []
    while queue:
        curr = queue.popleft()
        sorted_nodes.append(curr)
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Append any remaining nodes to avoid losing data on circular deps.
    if len(sorted_nodes) < len(model_classes):
        seen = set(sorted_nodes)
        for node in in_degree:
            if node not in seen:
                sorted_nodes.append(node)

    return [lookup[node] for node in sorted_nodes]


# ---------------------------------------------------------------------------
# Initial migration writer
# ---------------------------------------------------------------------------

def write_initial_migration(
    app_name: str,
    model_classes: list[type[Model]],
    migrations_dir: str,
    *,
    migration_name: str | None = None,
    dependencies: list[tuple[str, str]] | None = None,
) -> str:
    """Generate the initial migration file for *model_classes*.

    Args:
        app_name: Name of the app (used in the file header).
        model_classes: List of Model subclasses to include.
        migrations_dir: Path to the ``<app>/migrations/`` directory.
        migration_name: Optional custom filename stem (e.g. ``"0002_add_email"``).
            Defaults to ``"0001_initial"``.
        dependencies: Optional list of ``(app, migration_name)`` tuples.

    Returns:
        Absolute path to the written migration file.
    """
    validate_identifier(app_name, "app name")

    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    postgis_prefix = (
        '    migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS postgis;"),\n'
        if needs_postgis(model_classes)
        else ""
    )

    sorted_models = sort_models_topologically(model_classes)
    tables_code: list[str] = []
    extra_ops: list[str] = []

    for model_cls in sorted_models:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
        model_opts = getattr(model_cls, "_meta", None)
        if model_opts is not None and model_opts.virtual:
            continue

        validate_identifier(model_cls._table_name, f"table name for {model_cls.__name__}")

        cols = format_columns(model_cls)
        tables_code.append(
            f"    migrations.CreateTable(\n"
            f"        table_name={model_cls._table_name!r},\n"
            f"        columns=[\n"
            f"{cols}\n"
            f"        ],\n"
            f"    ),"
        )

        table_name = model_cls._table_name

        # Named meta indexes
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

        # Per-field db_index (non-unique, non-PK)
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

        # unique_together
        for ut_fields in getattr(model_cls, "_meta_unique_together", []):
            col_names = [
                model_cls._fields[f].column_name if f in model_cls._fields else f
                for f in ut_fields
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

        # Meta.constraints
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
                    f"\n        condition={constraint.condition!r},"
                    if constraint.condition
                    else ""
                )
                extra_ops.append(
                    f"    migrations.AddConstraint(\n"
                    f"        table_name={table_name!r},\n"
                    f"        constraint_name={constraint.name!r},\n"
                    f"        constraint_type='UNIQUE',\n"
                    f"        columns={constraint.fields!r},{cond_part}\n"
                    f"    ),"
                )

    tables_str = "\n".join(tables_code)
    if extra_ops:
        tables_str += "\n" + "\n".join(extra_ops)

    deps_str = repr(dependencies or [])
    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

    content = (
        f'"""Initial migration for {app_name!r}.\n\n'
        f"Auto-generated by OpenViper on {timestamp}.\n"
        f'"""\n\n'
        f"from openviper.db.migrations import executor as migrations\n\n"
        f"dependencies = {deps_str}\n\n"
        f"operations = [\n"
        f"{postgis_prefix}{tables_str}\n"
        f"]\n"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


# ---------------------------------------------------------------------------
# Migration numbering
# ---------------------------------------------------------------------------

def next_migration_number(migrations_dir: str) -> str:
    """Return the next zero-padded 4-digit migration number string."""
    existing = [
        f.stem for f in Path(migrations_dir).glob("*.py") if not f.stem.startswith("_")
    ]
    numbers: list[int] = []
    for name in existing:
        with contextlib.suppress(ValueError):
            numbers.append(int(name.split("_")[0]))
    return str(max(numbers, default=0) + 1).zfill(4)


# ---------------------------------------------------------------------------
# Model state snapshot
# ---------------------------------------------------------------------------

def model_state_snapshot(model_classes: list[type[Model]]) -> dict[str, dict[str, Any]]:
    """Build a deterministic snapshot of the current model definitions.

    Returns a mapping of ``{table_name: state_dict}`` where each state dict
    has the keys ``columns``, ``indexes``, ``unique_together``,
    ``index_together``, ``constraints``, ``single``, and ``managed``.
    """
    state: dict[str, dict[str, Any]] = {}
    for model_cls in model_classes:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
        model_opts = getattr(model_cls, "_meta", None)
        if model_opts is not None and model_opts.virtual:
            continue

        cols: list[dict[str, Any]] = []
        for _name, field in model_cls._fields.items():
            if field.column_type == "":
                continue
            col: dict[str, Any] = {
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
            cols.append(col)

        cols.sort(key=lambda c: c["name"])

        state[model_cls._table_name] = {
            "columns": cols,
            "indexes": build_model_indexes(model_cls),
            "unique_together": build_model_unique_together(model_cls),
            "index_together": build_model_index_together(model_cls),
            "constraints": build_model_constraints(model_cls),
            "single": getattr(model_cls, "_is_single", False),
            "managed": getattr(model_cls, "_is_managed", True),
        }
    return state


# ---------------------------------------------------------------------------
# Migrated state reconstruction from existing migration files
# ---------------------------------------------------------------------------

# Module-level cache of soft-removed columns, keyed by (table_name, column_name).
# Populated by read_migrated_state() / parse_remove_column(); consumed by
# check_was_soft_removed() and diff_states().
_soft_removed_columns: dict[tuple[str, str], dict[str, Any]] = {}


def read_migrated_state(migrations_dir: str) -> dict[str, dict[str, Any]]:
    """Reconstruct table state by replaying all existing migration files.

    Parses every ``*.py`` file in *migrations_dir* (in alphabetical order)
    and applies each operation to build up a schema state dict identical in
    structure to :func:`model_state_snapshot`.

    Returns:
        ``{table_name: state_dict}`` reflecting the database schema after all
        existing migrations have been applied.
    """
    _soft_removed_columns.clear()

    state: dict[str, dict[str, Any]] = {}
    mig_dir = Path(migrations_dir)
    if not mig_dir.is_dir():
        return state

    for mig_file in sorted(f for f in mig_dir.glob("*.py") if not f.stem.startswith("_")):
        source = mig_file.read_text()
        try:
            tree = ast.parse(source, filename=str(mig_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "operations"
                for target in node.targets
            ):
                continue
            if not isinstance(node.value, ast.List):
                continue
            for elt in node.value.elts:
                parse_operation(elt, state)

    return state


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def get_op_name(node: ast.Call) -> str | None:
    """Return the operation class name from an AST Call node."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def get_kw_str(node: ast.Call, key: str) -> str | None:
    """Extract a string keyword argument from an AST Call node, or None."""
    for kw in node.keywords:
        if kw.arg == key and isinstance(kw.value, ast.Constant):
            value = kw.value.value
            return value if isinstance(value, str) else None
    return None


def get_kw_bool(node: ast.Call, key: str, default: bool = False) -> bool:
    """Extract a boolean keyword argument from an AST Call node."""
    for kw in node.keywords:
        if kw.arg == key and isinstance(kw.value, ast.Constant):
            return bool(kw.value.value)
    return default


def ast_dict_to_dict(node: ast.Dict) -> dict[str, Any]:
    """Convert an ``ast.Dict`` of constant keys/values to a plain dict."""
    result: dict[str, Any] = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
            result[str(key.value)] = value.value
    return result


def ensure_table(state: dict[str, dict[str, Any]], table_name: str) -> None:
    """Insert a blank table entry if *table_name* is not already in *state*."""
    if table_name not in state:
        state[table_name] = {
            "columns": [],
            "indexes": [],
            "unique_together": [],
            "constraints": [],
        }


# ---------------------------------------------------------------------------
# Per-operation AST parsers
# ---------------------------------------------------------------------------

def parse_operation(node: ast.AST, state: dict[str, dict[str, Any]]) -> None:
    """Dispatch a single AST operation node to the appropriate parser."""
    if not isinstance(node, ast.Call):
        return
    op_name = get_op_name(node)
    if op_name is None:
        return

    dispatch: dict[str, Any] = {
        "CreateTable": parse_create_table,
        "CreateIndex": parse_create_index,
        "DropTable": parse_drop_table,
        "AddColumn": parse_add_column,
        "RemoveColumn": parse_remove_column,
        "AlterColumn": parse_alter_column,
        "RemoveIndex": parse_remove_index,
        "RenameColumn": parse_rename_column,
        "RestoreColumn": parse_restore_column,
        "AddConstraint": parse_add_constraint,
        "RemoveConstraint": parse_remove_constraint,
    }
    handler = dispatch.get(op_name)
    if handler is not None:
        handler(node, state)


def parse_create_table(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name: str | None = None
    columns: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    unique_together: list[list[str]] = []
    single: bool = False

    for kw in node.keywords:
        if kw.arg == "table_name" and isinstance(kw.value, ast.Constant):
            table_name = str(kw.value.value)
        elif kw.arg == "columns" and isinstance(kw.value, ast.List):
            for col_node in kw.value.elts:
                if isinstance(col_node, ast.Constant) and isinstance(col_node.value, dict):
                    columns.append(col_node.value)
                elif isinstance(col_node, ast.Dict):
                    col = ast_dict_to_dict(col_node)
                    if col:
                        columns.append(col)
        elif kw.arg == "constraints" and isinstance(kw.value, ast.List):
            for c_node in kw.value.elts:
                if isinstance(c_node, ast.Constant) and isinstance(c_node.value, dict):
                    constraints.append(c_node.value)
                elif isinstance(c_node, ast.Dict):
                    c = ast_dict_to_dict(c_node)
                    if c:
                        constraints.append(c)
        elif kw.arg == "unique_together" and isinstance(kw.value, ast.List):
            for ut_node in kw.value.elts:
                if isinstance(ut_node, ast.List):
                    ut_fields = [
                        str(elt.value)
                        for elt in ut_node.elts
                        if isinstance(elt, ast.Constant)
                    ]
                    if ut_fields:
                        unique_together.append(sorted(ut_fields))
        elif kw.arg == "single" and isinstance(kw.value, ast.Constant):
            single = bool(kw.value.value)

    if table_name is not None:
        columns.sort(key=lambda c: c.get("name", ""))
        unique_together.sort()
        constraints.sort(key=lambda c: c.get("name", ""))
        state[table_name] = {
            "columns": columns,
            "indexes": [],
            "unique_together": unique_together,
            "constraints": constraints,
            "single": single,
        }


def parse_drop_table(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    if table_name:
        state.pop(table_name, None)


def parse_create_index(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    index_name = get_kw_str(node, "index_name")
    if not table_name:
        return

    columns: list[str] = []
    unique = False
    for kw in node.keywords:
        if kw.arg == "columns" and isinstance(kw.value, ast.List):
            columns = [
                str(elt.value)
                for elt in kw.value.elts
                if isinstance(elt, ast.Constant)
            ]
        elif kw.arg == "unique" and isinstance(kw.value, ast.Constant):
            unique = bool(kw.value.value)

    ensure_table(state, table_name)
    if unique:
        state[table_name]["unique_together"].append(columns)
        state[table_name]["unique_together"].sort()
    else:
        state[table_name]["indexes"].append({"name": index_name, "fields": columns})
        state[table_name]["indexes"].sort(
            key=lambda x: x.get("name") or str(x.get("fields"))
        )


def parse_remove_index(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    index_name = get_kw_str(node, "index_name")
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


def parse_add_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    column_name = get_kw_str(node, "column_name")
    column_type = get_kw_str(node, "column_type")
    if not table_name or not column_name or not column_type:
        return

    nullable = True
    default: Any = None
    for kw in node.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = bool(kw.value.value)
        elif kw.arg == "default" and isinstance(kw.value, ast.Constant):
            default = kw.value.value

    col: dict[str, Any] = {"name": column_name, "type": column_type, "nullable": nullable}
    if default is not None:
        col["default"] = default

    ensure_table(state, table_name)
    cols = state[table_name]["columns"]
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def parse_remove_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    column_name = get_kw_str(node, "column_name")
    if not table_name or not column_name:
        return

    ensure_table(state, table_name)
    table_data = state[table_name]
    cols = table_data["columns"]

    removed_col: dict[str, Any] | None = None
    kept: list[dict[str, Any]] = []
    for c in cols:
        if c.get("name") == column_name:
            removed_col = dict(c)
        else:
            kept.append(c)

    # Honour an explicit column_type keyword if present (soft-remove metadata).
    explicit_type = get_kw_str(node, "column_type")
    if removed_col is None:
        removed_col = {"name": column_name, "type": explicit_type or "TEXT"}
    elif explicit_type:
        removed_col["type"] = explicit_type

    _soft_removed_columns[(table_name, column_name)] = removed_col
    table_data["columns"] = kept


def parse_alter_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    column_name = get_kw_str(node, "column_name")
    if not table_name or not column_name:
        return

    table_data = state.get(table_name)
    if not table_data:
        return

    # Check whether a ``default`` keyword was supplied at all (distinguishes
    # "set default to None" from "leave default unchanged").
    has_default_kw = any(kw.arg == "default" for kw in node.keywords)

    for col in table_data["columns"]:
        if col.get("name") != column_name:
            continue
        new_type = get_kw_str(node, "column_type")
        if new_type is not None:
            col["type"] = new_type
        for kw in node.keywords:
            if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                col["nullable"] = bool(kw.value.value)
            elif kw.arg == "default" and isinstance(kw.value, ast.Constant):
                col["default"] = kw.value.value
            elif kw.arg == "autoincrement" and isinstance(kw.value, ast.Constant):
                col["autoincrement"] = bool(kw.value.value)
            elif kw.arg == "primary_key" and isinstance(kw.value, ast.Constant):
                col["primary_key"] = bool(kw.value.value)
        if not has_default_kw:
            col.pop("default", None)
        break


def parse_rename_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    old_name = get_kw_str(node, "old_name")
    new_name = get_kw_str(node, "new_name")
    if not table_name or not old_name or not new_name:
        return

    table_data = state.get(table_name)
    if not table_data:
        return

    for col in table_data["columns"]:
        if col.get("name") == old_name:
            col["name"] = new_name
            break


def parse_restore_column(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    """Handle a RestoreColumn operation - re-add the column to state.

    The column was previously soft-removed (still in DB, tracked in
    ``openviper_soft_removed_columns``).  This adds it back to the migration
    state so the ORM recognises it again.
    """
    table_name = get_kw_str(node, "table_name")
    column_name = get_kw_str(node, "column_name")
    column_type = get_kw_str(node, "column_type")
    if not table_name or not column_name:
        return

    soft_info = _soft_removed_columns.pop((table_name, column_name), None)
    col: dict[str, Any] = {
        "name": column_name,
        "type": column_type or (soft_info.get("type", "TEXT") if soft_info else "TEXT"),
        "nullable": True,  # Restored columns are nullable until explicitly altered.
    }

    ensure_table(state, table_name)
    cols = state[table_name]["columns"]
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def parse_add_constraint(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    constraint_name = get_kw_str(node, "constraint_name")
    constraint_type = get_kw_str(node, "constraint_type")
    if not table_name or not constraint_name or not constraint_type:
        return

    ensure_table(state, table_name)
    constraint: dict[str, Any] = {
        "name": constraint_name,
        "type": constraint_type.upper(),
    }

    if constraint_type.upper() == "CHECK":
        check_expr = get_kw_str(node, "check")
        if check_expr:
            constraint["check"] = check_expr
    elif constraint_type.upper() == "UNIQUE":
        columns: list[str] = []
        for kw in node.keywords:
            if kw.arg == "columns" and isinstance(kw.value, ast.List):
                columns = [
                    str(elt.value)
                    for elt in kw.value.elts
                    if isinstance(elt, ast.Constant)
                ]
        constraint["fields"] = columns
        condition = get_kw_str(node, "condition")
        if condition:
            constraint["condition"] = condition

    state[table_name]["constraints"].append(constraint)
    state[table_name]["constraints"].sort(key=lambda c: c.get("name", ""))


def parse_remove_constraint(node: ast.Call, state: dict[str, dict[str, Any]]) -> None:
    table_name = get_kw_str(node, "table_name")
    constraint_name = get_kw_str(node, "constraint_name")
    if not table_name or not constraint_name or table_name not in state:
        return
    state[table_name]["constraints"] = [
        c for c in state[table_name].get("constraints", [])
        if c.get("name") != constraint_name
    ]


# ---------------------------------------------------------------------------
# State normalisation and diffing
# ---------------------------------------------------------------------------

def normalize_type_name(col_type: str) -> str:
    """Map a dialect-specific SQL type to its canonical base form.

    Allows cross-dialect comparison between types stored in migration files
    and the live database schema.
    """
    col_type = col_type.strip().upper()
    # Strip COLLATE clauses (PostgreSQL / SQLite)
    col_type = re.sub(r'\s+COLLATE\s+"[^"]*"', "", col_type)
    base = col_type.split("(")[0].strip()
    equivalents: dict[str, str] = {
        # Integer family
        "BOOLEAN": "INTEGER",
        "BIT": "INTEGER",
        "TINYINT": "INTEGER",
        "SMALLINT": "INTEGER",
        "BIGINT": "INTEGER",
        "INT": "INTEGER",
        "NUMBER": "INTEGER",
        # Text family
        "UUID": "TEXT",
        "UNIQUEIDENTIFIER": "TEXT",
        "JSON": "TEXT",
        "JSONB": "TEXT",
        "CLOB": "TEXT",
        "BLOB": "TEXT",
        "BYTEA": "TEXT",
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "NCHAR": "TEXT",
        "NVARCHAR": "TEXT",
        "NVARCHAR2": "TEXT",
        "VARCHAR2": "TEXT",
        "LONGTEXT": "TEXT",
        "MEDIUMTEXT": "TEXT",
        "TINYTEXT": "TEXT",
        "ENUM": "TEXT",
        # Datetime family
        "TIMESTAMP": "DATETIME",
        "TIMESTAMP WITH TIME ZONE": "DATETIME",
        "TIMESTAMP WITHOUT TIME ZONE": "DATETIME",
        "DATETIME2": "DATETIME",
        "DATETIMEOFFSET": "DATETIME",
        "SMALLDATETIME": "DATETIME",
        # Oracle DATE stores year/month/day/hour/minute/second
        "DATE": "DATETIME",
        # Time family
        "TIME WITH TIME ZONE": "TIME",
        "TIME WITHOUT TIME ZONE": "TIME",
        # Float family
        "DOUBLE": "FLOAT",
        "DOUBLE PRECISION": "FLOAT",
        "REAL": "FLOAT",
        "MONEY": "FLOAT",
        "SMALLMONEY": "FLOAT",
        # Large-object family
        "NTEXT": "TEXT",
        "IMAGE": "TEXT",
        "VARBINARY": "TEXT",
        "BINARY": "TEXT",
    }
    return equivalents.get(base, base)


def normalize_state(state: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a deep copy of *state* with volatile/dialect-specific fields stripped.

    Strips fields that cannot be reliably compared between JSON schema files
    and live database introspection across dialects (nullability, defaults,
    on_delete, single-column unique constraints encoded as UNIQUE indexes).
    """
    state = copy.deepcopy(state)
    for table_data in state.values():
        for col in table_data["columns"]:
            col.pop("field_class", None)
            col.pop("unique", None)
            col.pop("default", None)
            col.pop("nullable", None)
            col.pop("on_delete", None)
            col["autoincrement"] = bool(col.get("autoincrement", False))
            if col.get("type"):
                col["type"] = normalize_type_name(col["type"])

        ut = table_data.get("unique_together", [])
        if ut:
            table_data["unique_together"] = [sorted(fields) for fields in ut]

        it = table_data.get("index_together", [])
        if it:
            table_data["index_together"] = [sorted(fields) for fields in it]

        # Remove single-column UNIQUE constraints (already covered by the
        # per-column ``unique`` flag) and strip check/condition expressions
        # (not reliably round-tripped across dialects).
        filtered: list[dict[str, Any]] = []
        for c in table_data.get("constraints", []):
            c.pop("condition", None)
            c.pop("check", None)
            if (
                c.get("type", "").upper() == "UNIQUE"
                and len(c.get("fields", [])) == 1
            ):
                continue
            filtered.append(c)
        table_data["constraints"] = filtered

    return state


def has_model_changes(model_classes: list[type[Model]], migrations_dir: str) -> bool:
    """Return ``True`` if the live models differ from what existing migrations cover.

    Virtual models are excluded because they are not backed by database tables.
    """
    db_model_classes = [
        cls
        for cls in model_classes
        if not (getattr(cls, "_meta", None) is not None and cls._meta.virtual)
    ]
    if not db_model_classes:
        return False
    current = normalize_state(model_state_snapshot(db_model_classes))
    existing = normalize_state(read_migrated_state(migrations_dir))
    return current != existing


def check_was_soft_removed(
    column_name: str,
    table_name: str,
    existing: dict[str, dict[str, Any]],
    migrations_dir: str | None = None,
) -> dict[str, Any] | None:
    """Return the soft-removed column info dict if the column was soft-removed, else None."""
    return _soft_removed_columns.get((table_name, column_name))


# ---------------------------------------------------------------------------
# State diffing - produces a list of Operations
# ---------------------------------------------------------------------------

def diff_states(
    current: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> list[Operation]:
    """Compare *current* model state with *existing* migrated state.

    Returns a list of :class:`~openviper.db.migrations.executor.Operation`
    objects that would bring the database from *existing* to *current*.
    """
    # Keep raw (un-normalised) copies for fields that normalisation strips.
    current_raw = current
    existing_raw = existing
    current = normalize_state(current)
    existing = normalize_state(existing)

    ops: list[Operation] = []

    # ── New tables ────────────────────────────────────────────────────────────
    new_table_names = sorted(current.keys() - existing.keys())
    if new_table_names:
        # Topological sort within new tables so FK targets come first.
        adj: dict[str, list[str]] = {name: [] for name in new_table_names}
        in_degree: dict[str, int] = dict.fromkeys(new_table_names, 0)
        for name in new_table_names:
            for col in current[name]["columns"]:
                target = col.get("target_table")
                if target and target in adj and target != name:
                    adj[target].append(name)
                    in_degree[name] += 1

        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        sorted_new: list[str] = []
        while queue:
            curr_name = queue.popleft()
            sorted_new.append(curr_name)
            for neighbor in adj[curr_name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_new) < len(new_table_names):
            remaining = [n for n in new_table_names if n not in sorted_new]
            sorted_new.extend(remaining)

        for table_name in sorted_new:
            table_data = current_raw[table_name]
            ops.append(
                CreateTable(
                    table_name=table_name,
                    columns=table_data["columns"],
                    constraints=table_data.get("constraints", []),
                    unique_together=table_data.get("unique_together", []),
                    index_together=table_data.get("index_together", []),
                    single=table_data.get("single", False),
                )
            )

            for idx in table_data["indexes"]:
                index_name = (
                    idx.get("name") or f"idx_{table_name}_{'_'.join(idx['fields'])}"
                )
                ops.append(
                    CreateIndex(
                        table_name=table_name, index_name=index_name, columns=idx["fields"]
                    )
                )

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

    # ── Dropped tables ────────────────────────────────────────────────────────
    for table_name in sorted(existing.keys() - current.keys()):
        ops.append(DropTable(table_name=table_name))

    # ── Existing tables ───────────────────────────────────────────────────────
    for table_name in sorted(current.keys() & existing.keys()):
        cur_data_raw = current_raw[table_name]
        cur_data_norm = current[table_name]
        old_data_norm = existing[table_name]
        old_data_raw = existing_raw[table_name]

        cur_cols: dict[str, dict[str, Any]] = {c["name"]: c for c in cur_data_raw["columns"]}
        old_cols: dict[str, dict[str, Any]] = {c["name"]: c for c in old_data_raw["columns"]}
        cur_cols_norm: dict[str, dict[str, Any]] = {
            c["name"]: c for c in cur_data_norm["columns"]
        }
        old_cols_norm: dict[str, dict[str, Any]] = {
            c["name"]: c for c in old_data_norm["columns"]
        }

        added_col_names = cur_cols.keys() - old_cols.keys()
        removed_col_names = old_cols.keys() - cur_cols.keys()

        # Track which columns have already been accounted for via Rename/Restore.
        handled_added: set[str] = set()
        handled_removed: set[str] = set()

        # Renames: new col carries an ``old_name`` meta attribute.
        for col_name in sorted(added_col_names):
            new_col = cur_cols[col_name]
            old_name_meta = new_col.get("old_name")
            if not (old_name_meta and old_name_meta in old_cols):
                continue
            old_col = old_cols[old_name_meta]
            if not types_compatible(
                old_col.get("type", "TEXT"), new_col.get("type", "TEXT")
            ):
                raise MigrationError(f"Incompatible types for renamed column {col_name}")
            ops.append(
                RenameColumn(
                    table_name=table_name, old_name=old_name_meta, new_name=col_name
                )
            )
            handled_added.add(col_name)
            handled_removed.add(old_name_meta)

        # Legacy rename convention: old name stored as ``_removed_<col>``.
        for col_name in sorted(added_col_names - handled_added):
            removed_name = f"_removed_{col_name}"
            if removed_name not in old_cols:
                continue
            old_col = old_cols[removed_name]
            new_col = cur_cols[col_name]
            if not types_compatible(
                old_col.get("type", "TEXT"), new_col.get("type", "TEXT")
            ):
                raise MigrationError(f"Incompatible types for restored column {col_name}")
            ops.append(
                RenameColumn(
                    table_name=table_name, old_name=removed_name, new_name=col_name
                )
            )
            handled_added.add(col_name)
            handled_removed.add(removed_name)

        # Soft-restores: column was previously soft-removed.
        for col_name in sorted(added_col_names - handled_added):
            was_soft = check_was_soft_removed(col_name, table_name, existing)
            if not was_soft:
                continue
            new_col = cur_cols[col_name]
            if not types_compatible(
                was_soft.get("type", "TEXT"), new_col.get("type", "TEXT")
            ):
                raise MigrationError(
                    f"Incompatible types for soft-restored column {col_name}"
                )
            ops.append(
                RestoreColumn(
                    table_name=table_name,
                    column_name=col_name,
                    column_type=new_col["type"],
                )
            )
            if not new_col.get("nullable", True):
                print(
                    f"\n\033[93m"
                    f"WARNING: Restoring column '{col_name}' on table "
                    f"'{table_name}' as NOT NULL.\n"
                    f"  This column was previously soft-removed and may contain NULL values.\n"
                    f"  The migration will validate at runtime and fail if NULL rows exist.\n"
                    f"  Consider making the field nullable or providing a default value.\n"
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
            handled_added.add(col_name)

        # Plain new columns.
        for col_name in sorted(added_col_names - handled_added):
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

        # Removed columns.
        for col_name in sorted(removed_col_names - handled_removed):
            old_col = old_cols[col_name]
            ops.append(
                RemoveColumn(
                    table_name=table_name,
                    column_name=col_name,
                    column_type=old_col.get("type", "TEXT"),
                    drop=True,
                )
            )

        # ── Altered columns ───────────────────────────────────────────────────
        for col_name in sorted(cur_cols.keys() & old_cols.keys()):
            cur = cur_cols[col_name]
            old = old_cols[col_name]
            cur_norm = cur_cols_norm[col_name]
            old_norm = old_cols_norm[col_name]

            type_changed = cur_norm.get("type") != old_norm.get("type")
            pk_changed = cur_norm.get("primary_key") != old_norm.get("primary_key")
            unique_changed = cur.get("unique") != old.get("unique")
            auto_changed = cur_norm.get("autoincrement") != old_norm.get("autoincrement")

            if type_changed or pk_changed or unique_changed or auto_changed:
                ops.append(
                    AlterColumn(
                        table_name=table_name,
                        column_name=col_name,
                        column_type=cur.get("type") if type_changed else None,
                        old_type=old.get("type") if type_changed else None,
                        primary_key=cur_norm.get("primary_key") if pk_changed else None,
                        old_primary_key=old_norm.get("primary_key") if pk_changed else None,
                        unique=cur.get("unique") if unique_changed else None,
                        old_unique=old.get("unique") if unique_changed else None,
                        autoincrement=cur_norm.get("autoincrement") if auto_changed else None,
                        old_autoincrement=old_norm.get("autoincrement") if auto_changed else None,
                    )
                )

        # ── Index diffs ───────────────────────────────────────────────────────
        def _idx_key(idx: dict[str, Any], tbl: str) -> str:
            return idx.get("name") or f"idx_{tbl}_{'_'.join(idx['fields'])}"

        cur_indexes = {
            _idx_key(idx, table_name): idx
            for idx in cur_data_norm.get("indexes", [])
        }
        old_indexes = {
            _idx_key(idx, table_name): idx
            for idx in old_data_norm.get("indexes", [])
        }

        old_covered_cols: set[frozenset[str]] = {
            frozenset(idx["fields"]) for idx in old_indexes.values()
        }

        for idx_name in sorted(cur_indexes.keys() - old_indexes.keys()):
            idx = cur_indexes[idx_name]
            if frozenset(idx["fields"]) in old_covered_cols:
                continue
            ops.append(
                CreateIndex(
                    table_name=table_name, index_name=idx_name, columns=idx["fields"]
                )
            )

        for idx_name in sorted(old_indexes.keys() - cur_indexes.keys()):
            ops.append(RemoveIndex(table_name=table_name, index_name=idx_name))

        # ── unique_together diffs ─────────────────────────────────────────────
        cur_ut = {tuple(fields) for fields in cur_data_norm.get("unique_together", [])}
        old_ut = {tuple(fields) for fields in old_data_norm.get("unique_together", [])}

        for fields in sorted(cur_ut - old_ut):
            ops.append(
                CreateIndex(
                    table_name=table_name,
                    index_name=f"uniq_{table_name}_{'_'.join(fields)}",
                    columns=list(fields),
                    unique=True,
                )
            )

        for fields in sorted(old_ut - cur_ut):
            ops.append(
                RemoveIndex(
                    table_name=table_name,
                    index_name=f"uniq_{table_name}_{'_'.join(fields)}",
                )
            )

        # ── index_together diffs ──────────────────────────────────────────────
        cur_it = {tuple(fields) for fields in cur_data_norm.get("index_together", [])}
        old_it = {tuple(fields) for fields in old_data_norm.get("index_together", [])}

        for fields in sorted(cur_it - old_it):
            ops.append(
                CreateIndex(
                    table_name=table_name,
                    index_name=f"idx_{table_name}_{'_'.join(fields)}",
                    columns=list(fields),
                )
            )

        for fields in sorted(old_it - cur_it):
            ops.append(
                RemoveIndex(
                    table_name=table_name,
                    index_name=f"idx_{table_name}_{'_'.join(fields)}",
                )
            )

        # ── Constraint diffs ──────────────────────────────────────────────────
        cur_constraints = {c["name"]: c for c in cur_data_norm.get("constraints", [])}
        old_constraints = {c["name"]: c for c in old_data_norm.get("constraints", [])}

        for c_name in sorted(cur_constraints.keys() - old_constraints.keys()):
            c = cur_constraints[c_name]
            if c["type"] == "CHECK":
                ops.append(
                    AddConstraint(
                        table_name=table_name,
                        constraint_name=c["name"],
                        constraint_type="CHECK",
                        check=c.get("check", ""),
                    )
                )
            elif c["type"] == "UNIQUE":
                ops.append(
                    AddConstraint(
                        table_name=table_name,
                        constraint_name=c["name"],
                        constraint_type="UNIQUE",
                        columns=c.get("fields", []),
                        condition=c.get("condition", ""),
                    )
                )

        for c_name in sorted(old_constraints.keys() - cur_constraints.keys()):
            c = old_constraints[c_name]
            ops.append(
                RemoveConstraint(
                    table_name=table_name,
                    constraint_name=c_name,
                    constraint_type=c.get("type", "UNIQUE"),
                )
            )

        # ── Single-row constraint diff ────────────────────────────────────────
        cur_single = cur_data_raw.get("single", False)
        old_single = old_data_norm.get("single", False)
        if cur_single and not old_single:
            ops.append(
                AddConstraint(
                    table_name=table_name,
                    constraint_name=f"chk_{table_name}_single_row",
                    constraint_type="CHECK",
                    check="id = 1",
                )
            )
        elif old_single and not cur_single:
            ops.append(
                RemoveConstraint(
                    table_name=table_name,
                    constraint_name=f"chk_{table_name}_single_row",
                    constraint_type="CHECK",
                )
            )

    return ops


# ---------------------------------------------------------------------------
# Operation formatter
# ---------------------------------------------------------------------------

def format_operation(op: Operation) -> str:
    """Render a single :class:`Operation` as a Python source string."""

    if isinstance(op, CreateTable):
        col_lines = [f"        {col!r}," for col in op.columns]
        cols_str = "\n".join(col_lines)
        parts = [
            f"        table_name={op.table_name!r}",
            f"        columns=[\n{cols_str}\n        ]",
        ]
        if op.constraints:
            c_lines = [f"        {c!r}," for c in op.constraints]
            parts.append(
                f"        constraints=[\n{chr(10).join(c_lines)}\n        ]"
            )
        if op.unique_together:
            ut_lines = [f"        {ut!r}," for ut in op.unique_together]
            parts.append(
                f"        unique_together=[\n{chr(10).join(ut_lines)}\n        ]"
            )
        if op.single:
            parts.append(f"        single={op.single!r}")
        body = chr(10).join(p + "," for p in parts[:-1]) + chr(10) + parts[-1]
        return f"    migrations.CreateTable(\n{body},\n    ),"

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
        return (
            f"    migrations.RemoveIndex("
            f"table_name={op.table_name!r}, index_name={op.index_name!r}),"
        )

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
        if op.default is not UNSET:
            parts.append(
                "        default=None" if op.default is None else f"        default={op.default!r}"
            )
        if op.old_type is not None:
            parts.append(f"        old_type={op.old_type!r}")
        if op.old_nullable is not None:
            parts.append(f"        old_nullable={op.old_nullable!r}")
        if op.old_default is not UNSET:
            parts.append(
                "        old_default=None"
                if op.old_default is None
                else f"        old_default={op.old_default!r}"
            )
        if op.autoincrement is not None:
            parts.append(f"        autoincrement={op.autoincrement!r}")
        if op.old_autoincrement is not None:
            parts.append(f"        old_autoincrement={op.old_autoincrement!r}")
        if op.primary_key is not None:
            parts.append(f"        primary_key={op.primary_key!r}")
        if op.old_primary_key is not None:
            parts.append(f"        old_primary_key={op.old_primary_key!r}")
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
            return (
                f"    migrations.RunSQL(sql={op.sql!r}, reverse_sql={op.reverse_sql!r}),"
            )
        return f"    migrations.RunSQL({op.sql!r}),"

    return f"    # Unsupported operation: {op!r}"


def render_create_table(op: CreateTable) -> str:
    """Dedicated renderer for CreateTable to keep format_operation readable."""
    col_lines = [f"        {col!r}," for col in op.columns]
    cols_str = "\n".join(col_lines)
    lines: list[str] = [
        "    migrations.CreateTable(",
        f"        table_name={op.table_name!r},",
        "        columns=[",
        cols_str,
        "        ],",
    ]
    if op.constraints:
        lines.append("        constraints=[")
        for c in op.constraints:
            lines.append(f"            {c!r},")
        lines.append("        ],")
    if op.unique_together:
        lines.append("        unique_together=[")
        for ut in op.unique_together:
            lines.append(f"            {ut!r},")
        lines.append("        ],")
    if op.single:
        lines.append(f"        single={op.single!r},")
    lines.append("    ),")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Migration file writer (incremental)
# ---------------------------------------------------------------------------

def write_migration(
    app_name: str,
    operations: list[Operation],
    migrations_dir: str,
    *,
    migration_name: str | None = None,
    dependencies: list[tuple[str, str]] | None = None,
) -> str:
    """Generate a migration file containing *operations*.

    Unlike :func:`write_initial_migration`, this function accepts any list of
    :class:`~openviper.db.migrations.executor.Operation` objects.

    Args:
        app_name: Name of the app.
        operations: List of Operation objects to include.
        migrations_dir: Path to the migrations directory.
        migration_name: Optional custom filename stem.
        dependencies: List of ``(app, migration_name)`` dependency tuples.

    Returns:
        Absolute path to the written migration file.
    """
    validate_identifier(app_name, "app name")

    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    if needs_postgis_ops(operations):
        operations = [RunSQL("CREATE EXTENSION IF NOT EXISTS postgis;")] + list(operations)

    # Use the dedicated renderer for CreateTable; fall through to format_operation otherwise.
    rendered: list[str] = []
    for op in operations:
        if isinstance(op, CreateTable):
            rendered.append(render_create_table(op))
        else:
            rendered.append(format_operation(op))

    ops_str = "\n".join(rendered)
    deps_str = repr(dependencies or [])
    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

    content = (
        f'"""Migration for {app_name!r}.\n\n'
        f"Auto-generated by OpenViper on {timestamp}.\n"
        f'"""\n\n'
        f"from openviper.db.migrations import executor as migrations\n\n"
        f"dependencies = {deps_str}\n\n"
        f"operations = [\n"
        f"{ops_str}\n"
        f"]\n"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)
