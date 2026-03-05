"""Migration writer — generates migration files from model introspection."""

from __future__ import annotations

import ast
import contextlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.db.migrations.executor import Operation
    from openviper.db.models import Model
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
    _types_compatible,
)


def _format_columns(model_cls: type[Model]) -> str:
    lines = []
    from openviper.db.fields import ForeignKey

    for _name, field in model_cls._fields.items():
        if field._column_type == "":
            continue
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
                col["target_table"] = target_model._table_name
            elif isinstance(field.to, str):
                # Fallback to string name if not yet resolvable
                # But we need the table name. If it's 'auth.User', we might not know the table.
                # In OpenViper, we usually resolve it.
                pass
            col["on_delete"] = field.on_delete

        lines.append(f"        {col!r},")
    return "\n".join(lines)


def _sort_models_topologically(model_classes: list[type[Model]]) -> list[type[Model]]:
    """Sort models based on ForeignKey dependencies within the same app."""
    from collections import deque

    from openviper.db.fields import ForeignKey

    # map table_name -> Model
    lookup = {m._table_name: m for m in model_classes}
    # build adjacency list and in-degree count
    adj = {m._table_name: [] for m in model_classes}
    in_degree = {m._table_name: 0 for m in model_classes}

    for model_cls in model_classes:
        node = model_cls._table_name
        for field in model_cls._fields.values():
            if isinstance(field, ForeignKey):
                target = field.resolve_target()
                if target and target._table_name in lookup and target._table_name != node:
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
    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    tables_code = []
    # Sort models topologically to handle intra-app dependencies (e.g. Post before Comment)
    sorted_models = _sort_models_topologically(model_classes)
    for model_cls in sorted_models:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
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
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    content = f'''"""Initial migration for {app_name}.

Auto-generated by OpenViper on {timestamp}.
"""

from openviper.db.migrations import executor as migrations

dependencies = {deps_str}

operations = [
{tables_str}
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


def model_state_snapshot(model_classes: list[type[Model]]) -> dict[str, list[dict]]:
    """Build a deterministic snapshot of the current model state.

    Returns a dict mapping table names to sorted lists of column definition
    dicts.  Abstract models are excluded automatically.
    """
    state: dict[str, list[dict]] = {}
    for model_cls in model_classes:
        meta = getattr(model_cls, "Meta", None)
        if meta and getattr(meta, "abstract", False):
            continue
        cols: list[dict] = []
        for _name, field in model_cls._fields.items():
            if field._column_type == "":
                continue
            col: dict = {
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
        state[model_cls._table_name] = cols
    return state


def read_migrated_state(migrations_dir: str) -> dict[str, list[dict]]:
    """Read all existing migration files and reconstruct the table state.

    Parses each migration's ``operations`` list to extract ``CreateTable``
    calls and their column definitions, giving a picture of what the
    migrations already cover.

    Also populates the module-level ``_soft_removed_columns`` dict with
    any columns that were soft-removed and not yet restored.

    Returns the same structure as :func:`model_state_snapshot`.
    """
    # Reset soft-removed tracking for a clean parse
    _soft_removed_columns.clear()

    state: dict[str, list[dict]] = {}
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


def _parse_operation(node: ast.AST, state: dict[str, list[dict]]) -> None:
    """Extract table info from a single AST operation node."""
    if not isinstance(node, ast.Call):
        return

    op_name = _get_op_name(node)
    if op_name is None:
        return

    if op_name == "CreateTable":
        _parse_create_table(node, state)
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
    elif op_name == "RenameColumn":
        _parse_rename_column(node, state)
    elif op_name == "RestoreColumn":
        _parse_restore_column(node, state)


def _parse_create_table(node: ast.Call, state: dict[str, list[dict]]) -> None:
    """Handle a CreateTable operation."""
    table_name: str | None = None
    columns: list[dict] = []

    for kw in node.keywords:
        if kw.arg == "table_name" and isinstance(kw.value, ast.Constant):
            table_name = kw.value.value
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
        state[table_name] = columns


def _parse_add_column(node: ast.Call, state: dict[str, list[dict]]) -> None:
    """Handle an AddColumn operation."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    column_type = _get_keyword_str(node, "column_type")
    if not table_name or not column_name or not column_type:
        return

    # Determine nullable (default True in AddColumn)
    nullable = True
    for kw in node.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = bool(kw.value.value)

    col: dict[str, Any] = {
        "name": column_name,
        "type": column_type,
        "nullable": nullable,
    }

    cols = state.setdefault(table_name, [])
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def _parse_remove_column(node: ast.Call, state: dict[str, list[dict]]) -> None:
    """Handle a RemoveColumn operation."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    if not table_name or not column_name:
        return

    cols = state.get(table_name, [])
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

    state[table_name] = [c for c in cols if c.get("name") != column_name]


def _parse_alter_column(node: ast.Call, state: dict[str, list[dict]]) -> None:
    """Handle an AlterColumn operation — update the column dict in state."""
    table_name = _get_keyword_str(node, "table_name")
    column_name = _get_keyword_str(node, "column_name")
    if not table_name or not column_name:
        return

    cols = state.get(table_name, [])
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


def _parse_rename_column(node: ast.Call, state: dict[str, list[dict]]) -> None:
    """Handle a RenameColumn operation — update the column name in state."""
    table_name = _get_keyword_str(node, "table_name")
    old_name = _get_keyword_str(node, "old_name")
    new_name = _get_keyword_str(node, "new_name")
    if not table_name or not old_name or not new_name:
        return

    cols = state.get(table_name, [])
    for col in cols:
        if col.get("name") == old_name:
            col["name"] = new_name
            break


def _parse_restore_column(node: ast.Call, state: dict[str, list[dict]]) -> None:
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
    cols = state.setdefault(table_name, [])
    cols.append(col)
    cols.sort(key=lambda c: c.get("name", ""))


def _ast_dict_to_dict(node: ast.Dict) -> dict:
    """Convert an ast.Dict of constants to a plain dict."""
    result: dict = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
            result[key.value] = value.value
    return result


def has_model_changes(model_classes: list[type[Model]], migrations_dir: str) -> bool:
    """Return ``True`` if the models differ from what existing migrations cover."""
    current = model_state_snapshot(model_classes)
    existing = read_migrated_state(migrations_dir)
    return current != existing


# ── Diff-based migration generation ──────────────────────────────────────


# Global dict to track columns that have been soft-removed across migrations.
# Populated by read_migrated_state; maps (table_name, column_name) to col info.
_soft_removed_columns: dict[tuple[str, str], dict] = {}


def _check_was_soft_removed(
    column_name: str,
    table_name: str,
    existing: dict[str, list[dict]],
    migrations_dir: str | None = None,
) -> dict | None:
    """Check if a column was previously soft-removed.

    Returns the column info dict if it was soft-removed, else None.
    """
    key = (table_name, column_name)
    if key in _soft_removed_columns:
        return _soft_removed_columns[key]
    return None


def _diff_states(
    current: dict[str, list[dict]],
    existing: dict[str, list[dict]],
) -> list[Operation]:
    """Compare *current* model state with *existing* migrated state.

    Returns a list of :class:`Operation` objects that would bring the
    database from *existing* to *current*.
    """

    ops: list[Operation] = []

    # New tables
    new_table_names = sorted(current.keys() - existing.keys())
    if new_table_names:
        # We need to sort these topologically. Since we only have snapshots (dicts),
        # we can't easily use resolve_target().
        # However, CreateTable operations in snapshots ALREADY contain target_table for FKs.

        # Build dependency graph from snapshot column definitions
        adj = {name: [] for name in new_table_names}
        in_degree = dict.fromkeys(new_table_names, 0)

        for name in new_table_names:
            cols = current[name]
            for col in cols:
                target = col.get("target_table")
                if target and target in adj and target != name:
                    adj[target].append(name)
                    in_degree[name] += 1

        from collections import deque

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
            ops.append(CreateTable(table_name=table_name, columns=current[table_name]))

    # Dropped tables
    for table_name in sorted(existing.keys() - current.keys()):
        ops.append(DropTable(table_name=table_name))

    # Column-level diffs for tables that exist in both
    for table_name in sorted(current.keys() & existing.keys()):
        cur_cols = {c["name"]: c for c in current[table_name]}
        old_cols = {c["name"]: c for c in existing[table_name]}

        added_col_names = cur_cols.keys() - old_cols.keys()
        removed_col_names = old_cols.keys() - cur_cols.keys()

        # Check for previously soft-removed columns being reintroduced.
        # If a column named "foo" is being added and "foo" was formerly
        # in the existing state (now removed), generate a RestoreColumn
        # to re-enable it in the watch list.  If the _removed_foo
        # pattern still exists (legacy), handle that too.
        restored: set[str] = set()
        restored_old_names: set[str] = set()
        for col_name in sorted(added_col_names):
            # Check if this column was previously removed (still present
            # in DB but soft-removed via watch list).  We look for it
            # in removed_col_names as well as _removed_ prefixed names.
            removed_name = f"_removed_{col_name}"

            # New behavior: column stays with same name, just soft-removed
            # The column won't appear in old_cols directly since
            # _parse_remove_column strips it.  But if the column still
            # exists in the database (soft-removed), we detect it via
            # the fact that it was in a RemoveColumn operation previously.
            # For now, check the _removed_ legacy pattern:
            if removed_name in old_cols:
                old_col = old_cols[removed_name]
                new_col = cur_cols[col_name]
                old_type = old_col.get("type", "TEXT")
                new_type = new_col.get("type", "TEXT")

                if not _types_compatible(old_type, new_type):

                    print(
                        f"\n\033[91m"
                        f"{'=' * 70}\n"
                        f"ERROR: Cannot restore column '{col_name}' on table '{table_name}'\n"
                        f"{'=' * 70}\n"
                        f"\n"
                        f"Type mismatch detected:\n"
                        f"  Previously removed type: {old_type}\n"
                        f"  New field type:          {new_type}\n"
                        f"\n"
                        f"These types are incompatible. The migration cannot proceed.\n"
                        f"\n"
                        f"Possible solutions:\n"
                        f"  1. Use '--drop-columns' to drop the old column data\n"
                        f"  2. Keep the same field type as before\n"
                        f"  3. Manually migrate the data first\n"
                        f"\033[0m",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)

                ops.append(
                    RenameColumn(
                        table_name=table_name,
                        old_name=removed_name,
                        new_name=col_name,
                    )
                )
                restored.add(col_name)
                restored_old_names.add(removed_name)
                continue

        # Also check for soft-removed columns (new behavior where column
        # name stays the same but is tracked in openviper_soft_removed_columns).
        # Since read_migrated_state strips removed columns from state,
        # a column that was removed then re-added will appear as a new
        # AddColumn.  We convert it to a RestoreColumn if the column
        # already exists in the DB.
        for col_name in sorted(added_col_names - restored):
            # Check if there was a RemoveColumn for this column name
            # in any prior migration (the column still exists in DB).
            # We detect this by checking if a prior migration removed it.
            _was_soft_removed = _check_was_soft_removed(
                col_name, table_name, existing, migrations_dir=None
            )
            if _was_soft_removed:
                new_col = cur_cols[col_name]
                new_type = new_col.get("type", "TEXT")
                new_nullable = new_col.get("nullable", True)
                old_type = _was_soft_removed.get("type", "TEXT")

                if not _types_compatible(old_type, new_type):

                    print(
                        f"\n\033[91m"
                        f"{'=' * 70}\n"
                        f"ERROR: Cannot restore column '{col_name}' on table '{table_name}'\n"
                        f"{'=' * 70}\n"
                        f"\n"
                        f"Type mismatch detected:\n"
                        f"  Previously removed type: {old_type}\n"
                        f"  New field type:          {new_type}\n"
                        f"\n"
                        f"These types are incompatible. The migration cannot proceed.\n"
                        f"\n"
                        f"Possible solutions:\n"
                        f"  1. Use '--drop-columns' to drop the old column data\n"
                        f"  2. Keep the same field type as before\n"
                        f"  3. Manually migrate the data first\n"
                        f"\033[0m",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)

                # Warn about NOT NULL with potentially null data
                if not new_nullable:

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
                    RestoreColumn(
                        table_name=table_name,
                        column_name=col_name,
                        column_type=new_type,
                    )
                )
                # If the new field changes nullable/type, also emit an AlterColumn
                if not new_nullable:
                    ops.append(
                        AlterColumn(
                            table_name=table_name,
                            column_name=col_name,
                            column_type=new_type,
                            nullable=False,
                            old_type=old_type,
                            old_nullable=True,
                        )
                    )
                restored.add(col_name)

        # Added columns (skip any that were restored)
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

        # Removed columns (skip _removed_ columns that were just restored)
        for col_name in sorted(removed_col_names - restored_old_names):
            old_col = old_cols[col_name]
            ops.append(
                RemoveColumn(
                    table_name=table_name,
                    column_name=col_name,
                    column_type=old_col.get("type", "TEXT"),
                )
            )

        # Altered columns — detect changes in type, nullable, default, unique, field_class
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
    filename = f"{migration_name or '0001_initial'}.py"
    path = Path(migrations_dir) / filename

    ops_str = "\n".join(_format_operation(op) for op in operations)
    deps_str = repr(dependencies or [])
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    content = f'''"""Migration for {app_name}.

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
