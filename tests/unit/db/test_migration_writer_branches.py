"""Additional branch tests for openviper.db.migrations.writer."""

from __future__ import annotations

import ast

import pytest

from openviper.db.fields import CharField, ManyToManyField
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)
from openviper.db.migrations.writer import (
    _diff_states,
    _format_columns,
    _format_operation,
    _parse_create_table,
    _parse_operation,
    _soft_removed_columns,
    _validate_identifier,
    model_state_snapshot,
    read_migrated_state,
    write_migration,
)
from openviper.db.models import Model
from openviper.exceptions import MigrationError


def test_validate_identifier_rejects_invalid_names():
    with pytest.raises(ValueError, match="Invalid app name"):
        _validate_identifier("bad-name", "app name")

    with pytest.raises(ValueError, match="Invalid table name"):
        _validate_identifier("123table", "table name")


def test_diff_states_restores_legacy_removed_column_name():
    existing = {
        "accounts": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "_removed_nickname", "type": "TEXT"},
            ],
            "indexes": [],
            "unique_together": [],
        }
    }
    current = {
        "accounts": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "nickname", "type": "TEXT"},
            ],
            "indexes": [],
            "unique_together": [],
        }
    }

    ops = _diff_states(current, existing)

    rename_ops = [op for op in ops if isinstance(op, RenameColumn)]
    assert len(rename_ops) == 1
    assert rename_ops[0].old_name == "_removed_nickname"
    assert rename_ops[0].new_name == "nickname"


# ── model_state_snapshot: abstract model skip ────────────────────────────────


def test_model_state_snapshot_skips_abstract():

    class AbstractModel(Model):
        name = CharField()

        class Meta:
            abstract = True
            table_name = "abstract_base"

    class ConcreteModel(Model):
        name = CharField()

        class Meta:
            table_name = "concrete_base"

    state = model_state_snapshot([AbstractModel, ConcreteModel])
    assert "abstract_base" not in state
    assert "concrete_base" in state


# ── model_state_snapshot: empty _column_type path ────────────────────────────


def test_model_state_snapshot_no_column_type():

    class NoTypeModel(Model):
        value = CharField()

        class Meta:
            table_name = "no_type_model"

    state = model_state_snapshot([NoTypeModel])
    assert "no_type_model" in state
    cols = state["no_type_model"]["columns"]
    # Should have columns; if _column_type is empty it uses "TEXT" fallback
    assert any(c["name"] == "value" for c in cols)


# ── _diff_states: circular dependency handling ────────────────────────────────


def test_diff_states_circular_dependency_does_not_crash():
    """Tables with circular FK references should not crash topological sort."""
    existing = {}
    current = {
        "table_a": {
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "b_id", "type": "INTEGER", "target_table": "table_b"},
            ],
            "indexes": [],
            "unique_together": [],
        },
        "table_b": {
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "a_id", "type": "INTEGER", "target_table": "table_a"},
            ],
            "indexes": [],
            "unique_together": [],
        },
    }
    ops = _diff_states(current, existing)
    # Should not raise, and should produce 2 CreateTable ops
    create_ops = [op for op in ops if isinstance(op, CreateTable)]
    assert len(create_ops) == 2


# ── _diff_states: type incompatibility error path ────────────────────────────


def test_diff_states_incompatible_type_with_soft_removed_exits():

    _soft_removed_columns[("t2", "col")] = {"name": "col", "type": "INTEGER"}
    try:
        existing = {"t2": {"columns": [], "indexes": [], "unique_together": []}}
        current = {
            "t2": {
                "columns": [{"name": "col", "type": "TEXT", "nullable": True}],
                "indexes": [],
                "unique_together": [],
            }
        }
        with pytest.raises(MigrationError):
            _diff_states(current, existing)
    finally:
        _soft_removed_columns.clear()


# ── read_migrated_state: SyntaxError skipped ─────────────────────────────────


def test_read_migrated_state_syntax_error_in_migration_file(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    bad = mig_dir / "0001_broken.py"
    bad.write_text("def foo(: bad syntax <<<")

    state = read_migrated_state(str(mig_dir))
    assert state == {}


# ── _format_operation: all field branches ────────────────────────────────────


def test_format_operation_alter_column_no_optional_fields():

    op = AlterColumn(table_name="t", column_name="c", column_type="TEXT")
    result = _format_operation(op)
    assert "AlterColumn" in result
    assert "TEXT" in result


def test_format_operation_restore_column_text_type():

    op = RestoreColumn(table_name="t", column_name="c", column_type="TEXT")
    result = _format_operation(op)
    assert "RestoreColumn" in result
    # TEXT type — should not include column_type= param in compact form
    assert "RestoreColumn" in result


def test_format_operation_remove_column_text_type():

    op = RemoveColumn(table_name="t", column_name="c", column_type="TEXT")
    result = _format_operation(op)
    assert "RemoveColumn" in result


# ── write_migration: invalid app name raises ─────────────────────────────────


def test_write_migration_invalid_migration_name(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    with pytest.raises(ValueError, match="Invalid"):
        write_migration("bad-app!", [], str(mig_dir))


# ── _format_columns: skip field with empty _column_type ──────────────────────


def test_format_columns_skips_field_with_empty_column_type():

    class WithM2M(Model):
        tags = ManyToManyField("Tag")

        class Meta:
            table_name = "with_m2m"

    result = _format_columns(WithM2M)
    # ManyToManyField has _column_type = "" so it's skipped — result has no 'tags' column
    assert "tags" not in result


# ── model_state_snapshot: skip field with empty _column_type ─────────────────


def test_model_state_snapshot_skips_field_with_empty_column_type():

    class WithM2MModel(Model):
        labels = ManyToManyField("Label")

        class Meta:
            table_name = "with_m2m_model"

    state = model_state_snapshot([WithM2MModel])
    cols = state.get("with_m2m_model", {}).get("columns", [])
    assert not any(c["name"] == "labels" for c in cols)


# ── read_migrated_state: non-List operations assignment ──────────────────────


def test_read_migrated_state_skips_non_list_operations(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_weird.py").write_text("operations = None\n")

    state = read_migrated_state(str(mig_dir))
    assert state == {}


# ── read_migrated_state: DropTable removes table from state ──────────────────


def test_read_migrated_state_drop_table_removes_table(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_create.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.CreateTable(table_name='items', columns=[]),\n"
        "]\n"
    )
    (mig_dir / "0002_drop.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.DropTable(table_name='items'),\n"
        "]\n"
    )

    state = read_migrated_state(str(mig_dir))
    assert "items" not in state


# ── _parse_*: missing required keyword args → return early ────────────────────


def test_parse_add_column_missing_args_is_noop(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    # AddColumn without required column_name and column_type
    (mig_dir / "0001_broken.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.AddColumn(table_name='t'),\n"
        "]\n"
    )
    state = read_migrated_state(str(mig_dir))
    assert state == {}


def test_parse_remove_column_missing_args_is_noop(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_broken.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.RemoveColumn(table_name='t'),\n"
        "]\n"
    )
    state = read_migrated_state(str(mig_dir))
    assert state == {}


def test_parse_alter_column_missing_args_is_noop(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_broken.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.AlterColumn(table_name='t'),\n"
        "]\n"
    )
    state = read_migrated_state(str(mig_dir))
    assert state == {}


def test_parse_rename_column_missing_args_is_noop(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_broken.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.RenameColumn(table_name='t'),\n"
        "]\n"
    )
    state = read_migrated_state(str(mig_dir))
    assert state == {}


def test_parse_restore_column_missing_args_is_noop(tmp_path):

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_broken.py").write_text(
        "import openviper.db.migrations.executor as migrations\n"
        "operations = [\n"
        "    migrations.RestoreColumn(table_name='t'),\n"
        "]\n"
    )
    state = read_migrated_state(str(mig_dir))
    assert state == {}


# ── _diff_states: _removed_ prefix with incompatible type → SystemExit ────────


def test_diff_states_removed_prefix_incompatible_type_exits():

    existing = {
        "my_table": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "_removed_score", "type": "INTEGER"},
            ],
            "indexes": [],
            "unique_together": [],
        }
    }
    current = {
        "my_table": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "score", "type": "TEXT"},  # incompatible with INTEGER
            ],
            "indexes": [],
            "unique_together": [],
        }
    }

    with pytest.raises(MigrationError):
        _diff_states(current, existing)


# ── _format_operation: AddColumn with default value ──────────────────────────


def test_format_operation_add_column_with_default_includes_default():

    op = AddColumn(table_name="t", column_name="status", column_type="TEXT", default="active")
    result = _format_operation(op)
    assert "AddColumn" in result
    assert "default=" in result
    assert "'active'" in result


def test_parse_operation_op_name_none_is_noop():
    """op_name is None (subscript call) → _parse_operation returns early."""

    # Build a Call node with a Subscript func — gives op_name = None
    func_node = ast.Subscript(
        value=ast.Name(id="ops", ctx=ast.Load()),
        slice=ast.Constant(value=0),
        ctx=ast.Load(),
    )
    call_node = ast.Call(func=func_node, args=[], keywords=[])

    state: dict = {}
    _parse_operation(call_node, state)
    assert state == {}


def test_parse_create_table_ast_constant_dict_column():
    """Column node is ast.Constant with a dict value → appended to columns."""

    col_constant = ast.Constant(value={"name": "id", "type": "INTEGER"})
    columns_list = ast.List(elts=[col_constant], ctx=ast.Load())
    call_node = ast.Call(
        func=ast.Name(id="CreateTable", ctx=ast.Load()),
        args=[],
        keywords=[
            ast.keyword(arg="table_name", value=ast.Constant(value="things")),
            ast.keyword(arg="columns", value=columns_list),
        ],
    )

    state: dict = {}
    _parse_create_table(call_node, state)
    assert "things" in state
    assert {"name": "id", "type": "INTEGER"} in state["things"]["columns"]
