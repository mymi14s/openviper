import ast
import os
from unittest.mock import MagicMock, patch

import pytest

from openviper.db import fields
from openviper.db.fields import ForeignKey
from openviper.db.migrations import writer
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateTable,
    DropTable,
    Operation,
    RemoveColumn,
    RenameColumn,
    RestoreColumn,
)
from openviper.db.migrations.writer import _parse_create_table, _sort_models_topologically
from openviper.db.models import Model


class WriterTestModel(Model):
    username = fields.CharField(max_length=50)

    class Meta:
        table_name = "test_writer_tbl"


def test_format_columns():
    cols = writer._format_columns(WriterTestModel)

    assert "test_writer_tbl" in writer.model_state_snapshot([WriterTestModel])
    # The output of _format_columns is a string of repr dicts
    assert "'id'" in cols
    assert "'INTEGER'" in cols
    assert "'username'" in cols
    assert "VARCHAR" in cols


def test_model_state_snapshot():
    state = writer.model_state_snapshot([WriterTestModel])
    assert "test_writer_tbl" in state
    assert len(state["test_writer_tbl"]) == 2


def test_next_migration_number(tmp_path):
    assert writer.next_migration_number(str(tmp_path)) == "0001"

    (tmp_path / "0001_initial.py").touch()
    assert writer.next_migration_number(str(tmp_path)) == "0002"

    (tmp_path / "not_a_migration.py").touch()
    assert writer.next_migration_number(str(tmp_path)) == "0002"


def test_write_initial_migration(tmp_path):
    path = writer.write_initial_migration("auth", [WriterTestModel], str(tmp_path))
    assert os.path.exists(path)

    with open(path) as f:
        content = f.read()

    assert "dependencies = []" in content
    assert "CreateTable" in content
    assert "test_writer_tbl" in content


def test_write_migration(tmp_path):
    op = CreateTable(
        table_name="foo", columns=[{"name": "id", "type": "INTEGER", "primary_key": True}]
    )
    path = writer.write_migration(
        "core", [op], str(tmp_path), migration_name="0001_custom", dependencies=[("auth", "0001")]
    )

    with open(path) as f:
        content = f.read()

    assert "0001_custom" in path
    assert "('auth', '0001')" in content
    assert "CreateTable" in content
    assert "foo" in content


def test_format_operation():
    c = CreateTable(table_name="foo", columns=[{"name": "a", "type": "INT"}])
    res = writer._format_operation(c)
    assert "CreateTable(" in res
    assert "table_name='foo'" in res

    d = DropTable(table_name="foo")
    res2 = writer._format_operation(d)
    assert "DropTable(table_name='foo')" in res2

    a = AddColumn(table_name="foo", column_name="b", column_type="TEXT")
    res3 = writer._format_operation(a)
    assert "AddColumn(" in res3
    assert "column_name='b'" in res3

    r = RemoveColumn(table_name="foo", column_name="b", column_type="TEXT")
    res4 = writer._format_operation(r)
    assert "RemoveColumn(" in res4
    assert "column_name='b'" in res4

    alt = AlterColumn(table_name="foo", column_name="b", column_type="VARCHAR", old_type="TEXT")
    assert "AlterColumn(" in writer._format_operation(alt)

    ren = RenameColumn(table_name="foo", old_name="b", new_name="c")
    assert "RenameColumn(" in writer._format_operation(ren)

    rest = RestoreColumn(table_name="foo", column_name="b", column_type="TEXT")
    assert "RestoreColumn(" in writer._format_operation(rest)


def test_diff_states_create_drop():
    existing = {"old_table": [{"name": "id", "type": "INT"}]}
    current = {"new_table": [{"name": "id", "type": "INT"}]}

    ops = writer._diff_states(current, existing)
    assert len(ops) == 2
    assert isinstance(ops[0], CreateTable)
    assert ops[0].table_name == "new_table"
    assert isinstance(ops[1], DropTable)
    assert ops[1].table_name == "old_table"


def test_diff_states_columns():
    existing = {
        "t": [
            {"name": "id", "type": "INT"},
            {"name": "old_col", "type": "TEXT"},
            {"name": "alt_col", "type": "INT"},
        ]
    }
    current = {
        "t": [
            {"name": "id", "type": "INT"},
            {"name": "new_col", "type": "VARCHAR"},
            {"name": "alt_col", "type": "VARCHAR"},
        ]
    }

    ops = writer._diff_states(current, existing)
    # expect remove old_col, alter alt_col, add new_col
    assert len(ops) == 3

    types = [type(o) for o in ops]
    assert RemoveColumn in types
    assert AlterColumn in types
    assert AddColumn in types


def test_read_migrated_state(tmp_path):
    writer.write_initial_migration("test", [WriterTestModel], str(tmp_path))
    state = writer.read_migrated_state(str(tmp_path))
    assert "test_writer_tbl" in state
    assert len(state["test_writer_tbl"]) == 2


@patch("openviper.db.migrations.writer.model_state_snapshot")
@patch("openviper.db.migrations.writer.read_migrated_state")
def test_has_model_changes(mock_read, mock_snapshot, tmp_path):
    mock_snapshot.return_value = {"t": [{"name": "id", "type": "INT"}]}
    mock_read.return_value = {"t": [{"name": "id", "type": "INT"}]}
    assert writer.has_model_changes([WriterTestModel], str(tmp_path)) is False

    mock_snapshot.return_value = {"t": [{"name": "id", "type": "INT"}]}
    mock_read.return_value = {"t": [{"name": "id", "type": "TEXT"}]}
    assert writer.has_model_changes([WriterTestModel], str(tmp_path)) is True


def test_read_migrated_state_operations(tmp_path):
    mig = tmp_path / "0002_ops.py"
    mig.write_text("""
operations = [
    migrations.CreateTable(table_name="opstb", columns=[{"name": "a", "type": "INT"}],),
    migrations.AddColumn(table_name="opstb", column_name="b", column_type="TEXT", nullable=False),
    migrations.DropTable(table_name="opstb2"),
    migrations.RemoveColumn(table_name="opstb", column_name="a"),
    migrations.AlterColumn(
        table_name="opstb", column_name="b", column_type="VARCHAR",
        nullable=True, default="hi"
    ),
    migrations.RenameColumn(table_name="opstb", old_name="b", new_name="c"),
    migrations.RestoreColumn(table_name="opstb", column_name="d", column_type="JSON"),
    migrations.UnknownOp()
]
""")
    state = writer.read_migrated_state(str(tmp_path))
    assert "opstb" in state
    cols = {c["name"]: c for c in state["opstb"]}
    # 'a' is removed. 'b' added, altered, renamed to 'c'. 'd' restored.
    assert "a" not in cols
    assert "b" not in cols
    assert "c" in cols
    assert cols["c"]["type"] == "VARCHAR"
    assert "d" in cols

    # Assert missing SyntaxError skip
    bad = tmp_path / "0003_bad.py"
    bad.write_text("this is invalid python((")
    # Should not raise
    writer.read_migrated_state(str(tmp_path))


def test_diff_states_complex():
    existing = {"t": [{"name": "id", "type": "INT"}, {"name": "_removed_old_col", "type": "TEXT"}]}
    current = {
        "t": [
            {"name": "id", "type": "INT"},
            {"name": "old_col", "type": "TEXT"},  # Type matches, restored!
            {"name": "new_col", "type": "INT", "nullable": False, "default": 1},
        ]
    }

    ops = writer._diff_states(current, existing)
    types = [type(x) for x in ops]
    assert RenameColumn in types
    assert AddColumn in types

    # And check was soft removed block
    writer._soft_removed_columns[("t", "soft_removed")] = {"name": "soft_removed", "type": "INT"}
    cur2 = {"t": [{"name": "soft_removed", "type": "INT", "nullable": False}]}
    ex2 = {"t": []}

    ops2 = writer._diff_states(cur2, ex2)
    # RestoreColumn and AlterColumn (because it's not nullable)
    op_types = [type(x) for x in ops2]
    assert RestoreColumn in op_types
    assert AlterColumn in op_types


def test_writer_model_edge_cases():
    class AbsModel(Model):
        class Meta:
            abstract = True

    class UniqueModel(Model):
        u_field = fields.CharField(unique=True, default="a")
        m2m = fields.ManyToManyField(to="auth.User")

        class Meta:
            table_name = "uniq"

    state = writer.model_state_snapshot([AbsModel, UniqueModel])
    assert "uniq" in state
    cols = state["uniq"]
    assert len(cols) == 2  # id, u_field. m2m is skipped because _column_type=""
    u_col = next(c for c in cols if c["name"] == "u_field")
    assert u_col["unique"] is True
    assert u_col["default"] == "a"

    # Hit _format_columns and write_initial_migration with AbsModel/UniqueModel
    writer._format_columns(UniqueModel)


def test_write_initial_migration_abstract(tmp_path):
    class AbsModel(Model):
        class Meta:
            abstract = True

    writer.write_initial_migration("auth", [AbsModel], str(tmp_path))


def test_diff_states_type_mismatch():
    writer._soft_removed_columns.clear()
    existing = {"t": [{"name": "_removed_col", "type": "INT"}]}
    current = {"t": [{"name": "col", "type": "TEXT"}]}

    with pytest.raises(SystemExit):
        writer._diff_states(current, existing)


def test_diff_states_type_mismatch_soft():
    writer._soft_removed_columns[("t", "col")] = {"name": "col", "type": "INT"}
    existing = {"t": []}
    current = {"t": [{"name": "col", "type": "TEXT"}]}

    with pytest.raises(SystemExit):
        writer._diff_states(current, existing)


def test_read_migrated_state_no_dir(tmp_path):
    assert writer.read_migrated_state(str(tmp_path / "fake")) == {}


def test_ast_dict_to_dict_fallback(tmp_path):
    # simulate direct names
    mig = tmp_path / "0005_ast.py"
    mig.write_text("""
from openviper.db.migrations.executor import AddColumn, UnknownClass
operations = [
    AddColumn(table_name="t", column_name="c", column_type="T"),
    AddColumn(), # Missing kwargs returns early
    UnknownClass(table_name="foo", column_name="b"), # Not recognized
    "not a call node",
    (lambda: 1)(), # func not Attribute/Name
]
bad_operations = "not a list"
operations = "also not a list"

def fn():
    operations = [
        # CreateTable invalid column
        migrations.CreateTable(table_name="x", columns=["invalid_string_col"]),
        migrations.RemoveColumn(table_name="x"),
        migrations.AlterColumn(table_name="x"),
        migrations.RenameColumn(table_name="x"),
        migrations.RestoreColumn(table_name="x"),
        migrations.RemoveColumn(table_name="t", column_name="unknown_col", column_type="JSON"),
        migrations.RemoveColumn(
            table_name="t", column_name="c", column_type="JSON"
        ),  # overrides type
    ]
""")
    state = writer.read_migrated_state(str(tmp_path))
    assert "t" in state


def test_format_operation_extended():
    add = AddColumn(
        table_name="foo", column_name="b", column_type="TEXT", nullable=False, default=10
    )
    res = writer._format_operation(add)
    assert "nullable=False" in res
    assert "default=10" in res

    rem = RemoveColumn(table_name="foo", column_name="b", column_type="T", drop=True)
    assert "drop=True" in writer._format_operation(rem)
    assert "column_type='T'" in writer._format_operation(rem)

    alt = AlterColumn(
        table_name="foo",
        column_name="b",
        nullable=True,
        default=1,
        old_nullable=False,
        old_default=2,
    )
    s = writer._format_operation(alt)
    assert "old_nullable=False" in s
    assert "old_default=2" in s
    assert "nullable=True" in s
    assert "default=1" in s

    rest = RestoreColumn(table_name="foo", column_name="b")  # No type
    assert "RestoreColumn" in writer._format_operation(rest)

    rest2 = RestoreColumn(table_name="foo", column_name="c", column_type="JSON")
    assert "column_type='JSON'" in writer._format_operation(rest2)

    class FakeOp(Operation):
        def forward_sql(self):
            pass

        def backward_sql(self):
            pass

    assert "Unsupported" in writer._format_operation(FakeOp())


def test_format_columns_with_fk():

    class ParentModel(Model):
        class Meta:
            table_name = "writer_parent_tbl"

    class ChildModel(Model):
        parent = ForeignKey(ParentModel, on_delete="CASCADE")

        class Meta:
            table_name = "writer_child_tbl"

    cols = writer._format_columns(ChildModel)
    assert "writer_parent_tbl" in cols
    assert "CASCADE" in cols


def test_sort_models_topologically_with_fk_dep():

    class ParentTopo(Model):
        class Meta:
            table_name = "topo_parent"

    class ChildTopo(Model):
        parent = ForeignKey(ParentTopo, on_delete="CASCADE")

        class Meta:
            table_name = "topo_child"

    result = _sort_models_topologically([ChildTopo, ParentTopo])
    parent_idx = result.index(ParentTopo)
    child_idx = result.index(ChildTopo)
    assert parent_idx < child_idx


# ── New branch-coverage tests ──────────────────────────────────────────────────


def test_format_columns_fk_unresolvable_string():

    class UnresolvableChild(Model):
        parent = ForeignKey(to="nonexistent.NonexistentModel", on_delete="CASCADE")

        class Meta:
            table_name = "unresolv_child_tbl"

    # resolve_target() returns None for unknown string; on_delete is still serialized
    cols = writer._format_columns(UnresolvableChild)
    assert "CASCADE" in cols


def test_sort_models_topologically_circular():

    class ModelCircA(Model):
        class Meta:
            table_name = "topo_circ_a"

    class ModelCircB(Model):
        class Meta:
            table_name = "topo_circ_b"

    fk_a = MagicMock(spec=ForeignKey)
    fk_a.resolve_target.return_value = ModelCircB

    fk_b = MagicMock(spec=ForeignKey)
    fk_b.resolve_target.return_value = ModelCircA

    with patch.object(ModelCircA, "_fields", {"id": MagicMock(), "b": fk_a}):
        with patch.object(ModelCircB, "_fields", {"id": MagicMock(), "a": fk_b}):
            result = _sort_models_topologically([ModelCircA, ModelCircB])
            assert len(result) == 2


def test_parse_create_table_no_table_name():
    node = ast.parse("CreateTable(columns=[])").body[0].value
    state: dict = {}
    _parse_create_table(node, state)
    assert state == {}


def test_parse_create_table_constant_dict_column():
    node = ast.parse("CreateTable(table_name='synth', columns=[])").body[0].value
    # Inject a synthetic ast.Constant whose value is a dict (defensive branch)
    const_col = ast.Constant(value={"name": "synth_id", "type": "INT"})
    for kw in node.keywords:
        if kw.arg == "columns":
            kw.value.elts.append(const_col)
    state: dict = {}
    _parse_create_table(node, state)
    assert "synth" in state
    assert any(c.get("name") == "synth_id" for c in state["synth"])


def test_diff_states_new_tables_with_fk_dep():
    existing: dict = {}
    current = {
        "parent_dep_tbl": [{"name": "id", "type": "INT", "primary_key": True}],
        "child_dep_tbl": [
            {"name": "id", "type": "INT", "primary_key": True},
            {"name": "parent_id", "type": "INT", "target_table": "parent_dep_tbl"},
        ],
    }
    ops = writer._diff_states(current, existing)
    table_names = [op.table_name for op in ops if isinstance(op, CreateTable)]
    assert "parent_dep_tbl" in table_names
    assert "child_dep_tbl" in table_names
    assert table_names.index("parent_dep_tbl") < table_names.index("child_dep_tbl")


def test_diff_states_new_tables_circular_fk():
    existing: dict = {}
    current = {
        "circ_tbl_a": [
            {"name": "id", "type": "INT"},
            {"name": "b_id", "type": "INT", "target_table": "circ_tbl_b"},
        ],
        "circ_tbl_b": [
            {"name": "id", "type": "INT"},
            {"name": "a_id", "type": "INT", "target_table": "circ_tbl_a"},
        ],
    }
    ops = writer._diff_states(current, existing)
    table_names = [op.table_name for op in ops if isinstance(op, CreateTable)]
    assert len(table_names) == 2
    assert "circ_tbl_a" in table_names
    assert "circ_tbl_b" in table_names
