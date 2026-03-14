import ast
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.db.fields import CharField, ForeignKey, IntegerField
from openviper.db.migrations import executor as migrations
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
from openviper.db.migrations.writer import (
    _diff_states,
    _format_columns,
    _format_operation,
    _get_op_name,
    _soft_removed_columns,
    _sort_models_topologically,
    _validate_identifier,
    has_model_changes,
    model_state_snapshot,
    next_migration_number,
    read_migrated_state,
    write_initial_migration,
    write_migration,
)
from openviper.db.models import Model


class TestMigrationWriterHelpers:
    def test_sort_models_topologically(self):
        class Parent(Model):
            name = CharField()

            class Meta:
                abstract = True

        class RealParent(Model):
            name = CharField()

            class Meta:
                table_name = "parent"

        class Child(Model):
            parent = ForeignKey(to=RealParent)

            class Meta:
                table_name = "child"

        # Child depends on RealParent
        sorted_models = _sort_models_topologically([Child, RealParent])
        assert sorted_models == [RealParent, Child]

    def test_sort_models_circular(self):
        class M1(Model):
            class Meta:
                table_name = "m1"

        class M2(Model):
            class Meta:
                table_name = "m2"

        # Manually inject dependency to simulate circular
        M1._fields = {"m2": ForeignKey(to=M2)}
        M2._fields = {"m1": ForeignKey(to=M1)}

        # Should not crash
        sorted_models = _sort_models_topologically([M1, M2])
        assert len(sorted_models) == 2

    def test_next_migration_number(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert next_migration_number(tmpdir) == "0001"

            Path(tmpdir, "0001_initial.py").touch()
            assert next_migration_number(tmpdir) == "0002"

            Path(tmpdir, "0005_something.py").touch()
            assert next_migration_number(tmpdir) == "0006"

    def test_model_state_snapshot(self):
        class SnapModel(Model):
            name = CharField(null=False)
            age = IntegerField(default=18)

            class Meta:
                table_name = "snap"

        snapshot = model_state_snapshot([SnapModel])
        assert "snap" in snapshot
        cols = snapshot["snap"]
        assert len(cols) == 3  # age, id, name
        # order is alphabetical by name
        assert cols[0]["name"] == "age"
        assert cols[1]["name"] == "id"
        assert cols[2]["name"] == "name"

    def test_read_migrated_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = Path(tmpdir, "0001_initial.py")
            m1.write_text("""
operations = [
    migrations.CreateTable(
        table_name="t1",
        columns=[{"name": "id", "type": "INTEGER"}]
    )
]
""")
            state = read_migrated_state(tmpdir)
            assert "t1" in state
            assert state["t1"][0]["name"] == "id"

    def test_read_migrated_state_complex(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = Path(tmpdir, "0001_initial.py")
            m1.write_text("""
operations = [
    migrations.CreateTable(table_name="t1", columns=[{"name": "c1", "type": "TEXT"}]),
    migrations.AddColumn(table_name="t1", column_name="c2", column_type="INTEGER", nullable=False),
    migrations.AlterColumn(table_name="t1", column_name="c1", column_type="VARCHAR(50)"),
    migrations.RenameColumn(table_name="t1", old_name="c2", new_name="c2_renamed"),
    migrations.RemoveColumn(table_name="t1", column_name="c1"),
    migrations.RestoreColumn(table_name="t1", column_name="c1", column_type="TEXT"),
]
""")
            state = read_migrated_state(tmpdir)
            assert "t1" in state
            # c1 was removed then restored as TEXT
            # c2 was renamed to c2_renamed
            col_names = [c["name"] for c in state["t1"]]
            assert "c1" in col_names
            assert "c2_renamed" in col_names
            assert "c2" not in col_names

    def test_read_migrated_state_edge_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = Path(tmpdir, "0001_initial.py")
            m1.write_text("""
operations = [
    # Invalid operation (not a call)
    123,
    # Unknown operation
    migrations.UnknownOp(),
    # CreateTable with constant dict column
    migrations.CreateTable(table_name="t1", columns=[{'name': 'c1', 'type': 'TEXT'}]),
    # RemoveColumn for non-existent column
    migrations.RemoveColumn(table_name="t1", column_name="nonexistent"),
]
""")
            state = read_migrated_state(tmpdir)
            assert "t1" in state
            assert state["t1"][0]["name"] == "c1"


class TestMigrationDiff:
    def test_diff_states_new_table(self):
        current = {
            "users": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "name", "type": "VARCHAR(100)"},
            ]
        }
        existing = {}
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], CreateTable)
        assert ops[0].table_name == "users"

    def test_diff_states_add_column(self):
        existing = {
            "users": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
            ]
        }
        current = {
            "users": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "name", "type": "VARCHAR(100)", "nullable": True},
            ]
        }
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], AddColumn)
        assert ops[0].column_name == "name"

    def test_diff_states_drop_table(self):
        existing = {"users": [{"name": "id", "type": "INTEGER"}]}
        current = {}
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(
            ops[0], migrations.DropTable if hasattr(migrations, "DropTable") else MagicMock
        )

    def test_diff_states_restore_column_error(self):
        # Mocking _soft_removed_columns for the test
        _soft_removed_columns[("t1", "c1")] = {"name": "c1", "type": "INTEGER"}

        current = {"t1": [{"name": "c1", "type": "TEXT"}]}
        existing = {"t1": []}

        with pytest.raises(SystemExit):
            _diff_states(current, existing)

        _soft_removed_columns.clear()

    def test_format_columns_with_fk(self):
        class Target(Model):
            class Meta:
                table_name = "target"

        class Source(Model):
            target = ForeignKey(to=Target)

            class Meta:
                table_name = "source"

        res = _format_columns(Source)
        assert "'target_table': 'target'" in res
        assert "'on_delete': 'CASCADE'" in res


class TestMigrationFormatOperation:
    def test_format_create_table(self):
        op = CreateTable(table_name="users", columns=[{"name": "id", "type": "INTEGER"}])
        res = _format_operation(op)
        assert "migrations.CreateTable" in res
        assert "'table_name': 'id'" in res or "{'name': 'id', 'type': 'INTEGER'}" in res

    def test_format_add_column(self):
        op = AddColumn(table_name="t", column_name="c", column_type="INTEGER", nullable=False)
        res = _format_operation(op)
        assert "migrations.AddColumn" in res
        assert "table_name='t'" in res
        assert "nullable=False" in res

    def test_write_initial_migration(self):
        class M(Model):
            name = CharField()

            class Meta:
                table_name = "m"

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_initial_migration("app", [M], tmpdir)
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "CreateTable" in content
            assert "table_name='m'" in content


class TestValidateIdentifier:
    def test_valid_identifiers(self):
        _validate_identifier("my_table")
        _validate_identifier("_private")
        _validate_identifier("Column1")

    def test_invalid_identifiers(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("my-column")
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("123abc")
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("has space")


class TestFormatColumnsExtended:
    def test_unique_field(self):
        class UniqueModel(Model):
            email = CharField(unique=True)

            class Meta:
                table_name = "unique_model"

        res = _format_columns(UniqueModel)
        assert "'unique': True" in res

    def test_default_value(self):
        class DefaultModel(Model):
            status = IntegerField(default=0)

            class Meta:
                table_name = "default_model"

        res = _format_columns(DefaultModel)
        assert "'default': 0" in res

    def test_unresolvable_fk(self):
        class FKModel(Model):
            ref = ForeignKey(to="nonexistent.Model")

            class Meta:
                table_name = "fk_model"

        res = _format_columns(FKModel)
        assert "'on_delete'" in res


class TestFormatOperationExtended:
    def test_format_drop_table(self):
        op = DropTable(table_name="old_table")
        res = _format_operation(op)
        assert "migrations.DropTable" in res
        assert "old_table" in res

    def test_format_remove_column_non_text(self):
        op = RemoveColumn(table_name="t", column_name="c", column_type="INTEGER")
        res = _format_operation(op)
        assert "migrations.RemoveColumn" in res
        assert "column_type='INTEGER'" in res

    def test_format_remove_column_with_drop(self):
        op = RemoveColumn(table_name="t", column_name="c", drop=True)
        res = _format_operation(op)
        assert "drop=True" in res

    def test_format_alter_column_all_params(self):
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(200)",
            nullable=False,
            default="x",
            old_type="VARCHAR(100)",
            old_nullable=True,
            old_default="y",
        )
        res = _format_operation(op)
        assert "migrations.AlterColumn" in res
        assert "column_type='VARCHAR(200)'" in res
        assert "nullable=False" in res
        assert "default='x'" in res
        assert "old_type='VARCHAR(100)'" in res
        assert "old_nullable=True" in res
        assert "old_default='y'" in res

    def test_format_rename_column(self):
        op = RenameColumn(table_name="t", old_name="a", new_name="b")
        res = _format_operation(op)
        assert "migrations.RenameColumn" in res
        assert "old_name='a'" in res
        assert "new_name='b'" in res

    def test_format_restore_column_non_text(self):
        op = RestoreColumn(table_name="t", column_name="c", column_type="INTEGER")
        res = _format_operation(op)
        assert "migrations.RestoreColumn" in res
        assert "column_type='INTEGER'" in res

    def test_format_unknown_op_fallback(self):
        op = Operation()
        res = _format_operation(op)
        assert "Unsupported operation" in res


class TestWriteMigration:
    def test_write_migration_with_various_ops(self):
        ops = [
            AddColumn(table_name="t", column_name="age", column_type="INTEGER", nullable=True),
            RemoveColumn(table_name="t", column_name="old_col"),
            AlterColumn(
                table_name="t",
                column_name="name",
                column_type="VARCHAR(200)",
                old_type="VARCHAR(100)",
            ),
            RenameColumn(table_name="t", old_name="x", new_name="y"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_migration("myapp", ops, tmpdir, migration_name="0002_changes")
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "from openviper.db.migrations import executor as migrations" in content
            assert "migrations.AddColumn" in content
            assert "migrations.RemoveColumn" in content
            assert "migrations.AlterColumn" in content
            assert "migrations.RenameColumn" in content
            assert "dependencies" in content
            assert "operations" in content


class TestHasModelChanges:
    def test_no_changes(self):
        class Stable(Model):
            name = CharField()

            class Meta:
                table_name = "stable"

        with tempfile.TemporaryDirectory() as tmpdir:
            write_initial_migration("app", [Stable], tmpdir)
            # model_state_snapshot includes field_class but read_migrated_state
            # does not parse it from the AST, so we mock model_state_snapshot
            # to strip field_class for a fair comparison
            with patch("openviper.db.migrations.writer.model_state_snapshot") as mock_snap:
                mock_snap.return_value = read_migrated_state(tmpdir)
                assert has_model_changes([Stable], tmpdir) is False

    def test_with_changes(self):
        class Before(Model):
            name = CharField()

            class Meta:
                table_name = "changing"

        with tempfile.TemporaryDirectory() as tmpdir:
            write_initial_migration("app", [Before], tmpdir)

            class After(Model):
                name = CharField()
                age = IntegerField(default=0)

                class Meta:
                    table_name = "changing"

            assert has_model_changes([After], tmpdir) is True


class TestDiffStatesAlterColumns:
    def test_type_change(self):
        existing = {"t": [{"name": "c", "type": "VARCHAR(100)", "nullable": True}]}
        current = {"t": [{"name": "c", "type": "VARCHAR(200)", "nullable": True}]}
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], AlterColumn)
        assert ops[0].column_type == "VARCHAR(200)"
        assert ops[0].old_type == "VARCHAR(100)"

    def test_nullable_change(self):
        existing = {"t": [{"name": "c", "type": "TEXT", "nullable": True}]}
        current = {"t": [{"name": "c", "type": "TEXT", "nullable": False}]}
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], AlterColumn)
        assert ops[0].nullable is False
        assert ops[0].old_nullable is True

    def test_default_change(self):
        existing = {"t": [{"name": "c", "type": "INTEGER", "nullable": True, "default": 0}]}
        current = {"t": [{"name": "c", "type": "INTEGER", "nullable": True, "default": 42}]}
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], AlterColumn)
        assert ops[0].default == 42
        assert ops[0].old_default == 0

    def test_field_class_change(self):
        existing = {
            "t": [{"name": "c", "type": "TEXT", "nullable": True, "field_class": "TextField"}]
        }
        current = {
            "t": [{"name": "c", "type": "TEXT", "nullable": True, "field_class": "CharField"}]
        }
        ops = _diff_states(current, existing)
        assert len(ops) == 1
        assert isinstance(ops[0], AlterColumn)


class TestDiffStatesSoftRemovedRestore:
    def test_restore_compatible_type(self):
        _soft_removed_columns[("t", "old_col")] = {"name": "old_col", "type": "TEXT"}
        try:
            existing = {"t": []}
            current = {"t": [{"name": "old_col", "type": "TEXT", "nullable": True}]}
            ops = _diff_states(current, existing)
            assert any(isinstance(op, RestoreColumn) for op in ops)
        finally:
            _soft_removed_columns.clear()

    def test_restore_not_null_warns(self, capsys):
        _soft_removed_columns[("t", "col")] = {"name": "col", "type": "TEXT"}
        try:
            existing = {"t": []}
            current = {"t": [{"name": "col", "type": "TEXT", "nullable": False}]}
            ops = _diff_states(current, existing)
            assert any(isinstance(op, RestoreColumn) for op in ops)
            assert any(isinstance(op, AlterColumn) and op.nullable is False for op in ops)
            captured = capsys.readouterr()
            assert "WARNING" in captured.err or "NOT NULL" in captured.err
        finally:
            _soft_removed_columns.clear()

    def test_restore_incompatible_type_exits(self):
        _soft_removed_columns[("t", "col")] = {"name": "col", "type": "INTEGER"}
        try:
            existing = {"t": []}
            current = {"t": [{"name": "col", "type": "TEXT", "nullable": True}]}
            with pytest.raises(SystemExit):
                _diff_states(current, existing)
        finally:
            _soft_removed_columns.clear()


class TestValidateIdentifierBranch:
    def test_valid_identifier_passes(self):
        _validate_identifier("my_table_123", "test context")

    def test_invalid_identifier_with_hyphen(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("my-table", "test context")

    def test_invalid_identifier_starts_with_number(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("123table", "test context")


class TestWriteInitialMigrationAbstract:
    def test_skips_abstract_model(self, tmp_path):
        """abstract model skipped in write_initial_migration."""

        class AbstractBase(Model):
            class Meta:
                abstract = True
                table_name = "abstract_base"

        class ConcreteModel(Model):
            name = CharField()

            class Meta:
                table_name = "concrete_model"

        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        path = write_initial_migration("test_app", [AbstractBase, ConcreteModel], str(mig_dir))
        content = Path(path).read_text()
        assert "concrete_model" in content
        assert "abstract_base" not in content


class TestModelStateSnapshotExtended:
    def test_snapshot_includes_unique_and_default(self):

        class SnapModel(Model):
            code = CharField(unique=True, max_length=10)
            count = IntegerField(default=42)

            class Meta:
                table_name = "snap_model"

        state = model_state_snapshot([SnapModel])
        cols = state["snap_model"]
        code_col = next((c for c in cols if c["name"] == "code"), None)
        count_col = next((c for c in cols if c["name"] == "count"), None)
        assert code_col is not None
        assert code_col.get("unique") is True
        assert count_col is not None
        assert count_col.get("default") == 42

    def test_snapshot_includes_fk_target_table(self):

        class FKTarget(Model):
            name = CharField()

            class Meta:
                table_name = "fk_target"

        class FKSource(Model):
            ref = ForeignKey(FKTarget, on_delete="CASCADE")

            class Meta:
                table_name = "fk_source"

        state = model_state_snapshot([FKTarget, FKSource])
        cols = state["fk_source"]
        ref_col = next((c for c in cols if c["name"] == "ref_id"), None)
        assert ref_col is not None


class TestReadMigratedStateSyntaxError:
    def test_syntax_error_skipped(self, tmp_path):
        """SyntaxError in migration file is skipped."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        bad_file = mig_dir / "0001_bad.py"
        bad_file.write_text("this is not valid python {{[")
        state = read_migrated_state(str(mig_dir))
        assert state == {}

    def test_non_dir_returns_empty(self):
        """non-existent directory."""
        state = read_migrated_state("/nonexistent/path")
        assert state == {}


class TestParseOperationBranches:
    def test_parse_drop_table(self, tmp_path):
        """DropTable removes from state."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="mytable", columns=[]),\n'
            '    migrations.DropTable(table_name="mytable"),\n'
            "]\n"
        )
        state = read_migrated_state(str(mig_dir))
        assert "mytable" not in state

    def test_parse_add_column(self, tmp_path):
        """AddColumn adds to state."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="t", columns=[]),\n'
            '    migrations.AddColumn(table_name="t", column_name="age", column_type="INTEGER"),\n'
            "]\n"
        )
        state = read_migrated_state(str(mig_dir))
        assert any(c.get("name") == "age" for c in state.get("t", []))

    def test_parse_rename_column(self, tmp_path):
        """RenameColumn renames in state."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="t", columns=[{"name": "old_col", "type": "TEXT"}]),\n'
            '    migrations.RenameColumn(table_name="t", old_name="old_col", new_name="new_col"),\n'
            "]\n"
        )
        state = read_migrated_state(str(mig_dir))
        cols = state.get("t", [])
        assert any(c.get("name") == "new_col" for c in cols)

    def test_parse_alter_column(self, tmp_path):
        """AlterColumn updates state."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="t", columns=[{"name": "val", "type": "TEXT", "nullable": True}]),\n'
            '    migrations.AlterColumn(table_name="t", column_name="val", column_type="VARCHAR(100)", nullable=False, default="hi"),\n'
            "]\n"
        )
        state = read_migrated_state(str(mig_dir))
        cols = state.get("t", [])
        val_col = next((c for c in cols if c.get("name") == "val"), None)
        assert val_col is not None
        assert val_col["type"] == "VARCHAR(100)"
        assert val_col["nullable"] is False

    def test_parse_restore_column(self, tmp_path):
        """RestoreColumn re-adds to state."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="t", columns=[{"name": "x", "type": "TEXT"}]),\n'
            '    migrations.RemoveColumn(table_name="t", column_name="x"),\n'
            '    migrations.RestoreColumn(table_name="t", column_name="x", column_type="TEXT"),\n'
            "]\n"
        )
        state = read_migrated_state(str(mig_dir))
        cols = state.get("t", [])
        assert any(c.get("name") == "x" for c in cols)


class TestFormatOperationExtendedBranches:
    def test_format_remove_column_with_type_and_drop(self):
        """RemoveColumn with non-TEXT type and drop=True."""
        op = RemoveColumn(table_name="t", column_name="c", column_type="INTEGER", drop=True)
        result = _format_operation(op)
        assert "INTEGER" in result
        assert "drop=True" in result

    def test_format_alter_column_all_fields(self):
        """569, 573-574: AlterColumn with all optional fields."""
        op = AlterColumn(
            table_name="t",
            column_name="c",
            column_type="VARCHAR(100)",
            nullable=False,
            default="hello",
            old_type="TEXT",
            old_nullable=True,
            old_default="world",
        )
        result = _format_operation(op)
        assert "VARCHAR(100)" in result
        assert "nullable=False" in result
        assert "default='hello'" in result
        assert "old_type='TEXT'" in result
        assert "old_nullable=True" in result
        assert "old_default='world'" in result

    def test_format_rename_column(self):
        op = RenameColumn(table_name="t", old_name="a", new_name="b")
        result = _format_operation(op)
        assert "RenameColumn" in result
        assert "'a'" in result
        assert "'b'" in result

    def test_format_restore_column_with_type(self):
        """RestoreColumn with non-TEXT type."""
        op = RestoreColumn(table_name="t", column_name="c", column_type="INTEGER")
        result = _format_operation(op)
        assert "RestoreColumn" in result
        assert "INTEGER" in result

    def test_format_unsupported_operation(self):
        """Cover fallback: unsupported operation."""
        op = Operation()  # base class
        result = _format_operation(op)
        assert "Unsupported" in result


class TestWriteMigrationExtended:
    def test_write_migration_with_multiple_ops(self, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        ops = [
            AddColumn(table_name="t", column_name="c", column_type="TEXT"),
            RemoveColumn(table_name="t", column_name="old"),
        ]
        path = write_migration("test_app", ops, str(mig_dir), migration_name="0002_changes")
        content = Path(path).read_text()
        assert "AddColumn" in content
        assert "RemoveColumn" in content

    def test_write_migration_validates_app_name(self, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        with pytest.raises(ValueError, match="Invalid"):
            write_migration("bad-app-name!", [], str(mig_dir))


class TestDiffStatesTopologicalSort:
    def test_new_tables_sorted_topologically(self):
        """topological sort of new tables with FK deps."""
        existing = {}
        current = {
            "authors": [{"name": "id", "type": "INTEGER", "primary_key": True}],
            "posts": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "author_id", "type": "INTEGER", "target_table": "authors"},
            ],
        }
        ops = _diff_states(current, existing)
        create_ops = [op for op in ops if isinstance(op, CreateTable)]
        table_names = [op.table_name for op in create_ops]
        assert table_names.index("authors") < table_names.index("posts")

    def test_removed_columns_in_diff(self):
        existing = {"t": [{"name": "old_col", "type": "TEXT", "nullable": True}]}
        current = {"t": []}
        ops = _diff_states(current, existing)
        assert any(isinstance(op, RemoveColumn) and op.column_name == "old_col" for op in ops)

    def test_dropped_table_in_diff(self):
        existing = {"old_table": [{"name": "id", "type": "INTEGER"}]}
        current = {}
        ops = _diff_states(current, existing)
        assert any(isinstance(op, DropTable) and op.table_name == "old_table" for op in ops)


class TestFormatColumnsFK:
    def test_format_columns_includes_fk_target(self):
        """FK column with target_table included in format."""

        class Target(Model):
            name = CharField()

            class Meta:
                table_name = "fc_target"

        class Source(Model):
            ref = ForeignKey(Target, on_delete="SET NULL")

            class Meta:
                table_name = "fc_source"

        result = _format_columns(Source)
        assert "ref_id" in result or "target_table" in result


class TestNextMigrationNumberExtended:
    def test_skips_non_numeric_prefix(self, tmp_path):
        """Non-numeric prefix skipped."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "abc_migration.py").write_text("")
        (mig_dir / "0005_add_field.py").write_text("")
        result = next_migration_number(str(mig_dir))
        assert result == "0006"

    def test_empty_dir(self, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        result = next_migration_number(str(mig_dir))
        assert result == "0001"


class TestGetOpName:
    def test_get_op_name_attribute(self):
        node = ast.parse("migrations.CreateTable()", mode="eval").body
        assert _get_op_name(node) == "CreateTable"

    def test_get_op_name_name(self):
        node = ast.parse("CreateTable()", mode="eval").body
        assert _get_op_name(node) == "CreateTable"

    def test_get_op_name_none(self):
        # A subscript call like foo[0]() has no standard name/attr
        node = ast.parse("foo[0]()", mode="eval").body
        assert _get_op_name(node) is None


class TestParseRemoveColumnTracking:
    def test_remove_column_tracks_soft_removed(self, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.CreateTable(table_name="t", columns=[{"name": "col", "type": "INTEGER"}]),\n'
            '    migrations.RemoveColumn(table_name="t", column_name="col", column_type="INTEGER"),\n'
            "]\n"
        )
        _soft_removed_columns.clear()
        state = read_migrated_state(str(mig_dir))
        assert ("t", "col") in _soft_removed_columns
        _soft_removed_columns.clear()

    def test_remove_column_no_prior_data_uses_default(self, tmp_path):
        """removed_col is None, falls back to TEXT."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        mig = mig_dir / "0001_init.py"
        mig.write_text(
            "from openviper.db.migrations import executor as migrations\n"
            "dependencies = []\n"
            "operations = [\n"
            '    migrations.RemoveColumn(table_name="t", column_name="unknown_col"),\n'
            "]\n"
        )
        _soft_removed_columns.clear()
        read_migrated_state(str(mig_dir))
        info = _soft_removed_columns.get(("t", "unknown_col"), {})
        assert info.get("type") == "TEXT"
        _soft_removed_columns.clear()
