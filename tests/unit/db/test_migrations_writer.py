"""Additional unit tests for openviper.db.migrations.writer.

These tests focus on safety/formatting branches that are easy to miss in the
larger migration writer suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.db.migrations.executor import Operation
from openviper.db.migrations.writer import (
    format_columns,
    format_operation,
    next_migration_number,
    write_initial_migration,
)


class DummyField:
    def __init__(
        self,
        *,
        column_name: str,
        column_type: str,
        null: bool = True,
        primary_key: bool = False,
        auto_increment: bool = False,
        unique: bool = False,
        db_index: bool = False,
        default=None,
    ) -> None:
        self.column_name = column_name
        self._column_type = column_type
        self.null = null
        self.primary_key = primary_key
        self.auto_increment = auto_increment
        self.unique = unique
        self.db_index = db_index
        self.default = default


def testformat_columns_rejects_invalid_column_identifier() -> None:
    class BadModel:
        __name__ = "BadModel"
        _fields = {"bad": DummyField(column_name="bad-name", column_type="TEXT")}

    with pytest.raises(ValueError, match="Invalid column name"):
        format_columns(BadModel)


def testformat_columns_rejects_invalid_fk_target_table_identifier() -> None:
    class DummyForeignKey:
        def __init__(self) -> None:
            self._column_type = "INTEGER"
            self.column_name = "owner_id"
            self.null = True
            self.primary_key = False
            self.auto_increment = False
            self.unique = False
            self.default = None
            self.on_delete = "CASCADE"
            self.to = "app.Model"

        def resolve_target(self):
            target = MagicMock()
            target._table_name = "bad-target-name"
            return target

    class FKModel:
        __name__ = "FKModel"
        _fields = {"owner": DummyForeignKey()}

    with patch("openviper.db.migrations.writer.ForeignKey", DummyForeignKey):
        with pytest.raises(ValueError, match="Invalid target table name"):
            format_columns(FKModel)


def test_write_initial_migration_includes_unique_together_indexes(tmp_path: Path) -> None:
    class ModelWithUniqueTogether:
        __name__ = "ModelWithUniqueTogether"
        _table_name = "things"
        _meta_indexes: list = []
        _meta_unique_together = [("a", "b")]
        _fields = {
            "id": DummyField(
                column_name="id",
                column_type="INTEGER",
                null=False,
                primary_key=True,
                auto_increment=True,
            ),
            "a": DummyField(column_name="a", column_type="TEXT"),
            "b": DummyField(column_name="b", column_type="TEXT"),
        }

        class Meta:
            abstract = False

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    path = write_initial_migration("test_app", [ModelWithUniqueTogether], str(mig_dir))
    content = Path(path).read_text()

    assert "CreateIndex" in content
    assert "unique=True" in content
    assert "uniq_things_a_b" in content


def test_write_initial_migration_indexes_resolve_fk_column_names(tmp_path: Path) -> None:
    class _FKField(DummyField):
        def __init__(self, *, column_name: str) -> None:
            super().__init__(column_name=column_name, column_type="INTEGER")
            self._is_fk = True

    class _IdxDef:
        def __init__(self, fields: list[str], name: str | None = None) -> None:
            self.fields = fields
            self.name = name

    class ModelWithFKIndex:
        __name__ = "ModelWithFKIndex"
        _table_name = "fk_things"
        _meta_unique_together: list = []
        _meta_indexes = [_IdxDef(["owner"])]
        _fields = {
            "id": DummyField(
                column_name="id", column_type="INTEGER", primary_key=True, auto_increment=True
            ),
            "owner": _FKField(column_name="owner_id"),
        }

        class Meta:
            abstract = False

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    path = write_initial_migration("test_app", [ModelWithFKIndex], str(mig_dir))
    content = Path(path).read_text()

    assert "owner_id" in content
    assert "idx_fk_things_owner_id" in content


def test_write_initial_migration_emits_db_index_field(tmp_path: Path) -> None:
    class ModelWithDbIndex:
        __name__ = "ModelWithDbIndex"
        _table_name = "indexed_things"
        _meta_indexes: list = []
        _meta_unique_together: list = []
        _fields = {
            "id": DummyField(
                column_name="id", column_type="INTEGER", primary_key=True, auto_increment=True
            ),
            "email": DummyField(column_name="email", column_type="VARCHAR(254)", db_index=True),
        }

        class Meta:
            abstract = False

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    path = write_initial_migration("test_app", [ModelWithDbIndex], str(mig_dir))
    content = Path(path).read_text()

    assert "idx_indexed_things_email" in content
    assert "'email'" in content


def test_next_migration_number_ignores_non_numeric_prefixes(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    (mig_dir / "abcd_not_a_number.py").write_text("# noop\n")
    assert next_migration_number(str(mig_dir)) == "0001"


def testformat_operation_fallback_for_unknown_operation() -> None:
    class Unknown(Operation):
        pass

    formatted = format_operation(Unknown())
    assert "Unsupported operation" in formatted


class TestDiffStatesAutoincrement:
    """Tests for diff_states detecting autoincrement and primary_key changes."""

    def test_diff_states_detects_autoincrement_change(self) -> None:
        from openviper.db.migrations.writer import diff_states

        old_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": True,
                    },
                    {"name": "title", "type": "TEXT", "nullable": True},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        new_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": True,
                        "autoincrement": True,
                    },
                    {"name": "title", "type": "TEXT", "nullable": True},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        ops = diff_states(new_state, old_state)
        alter_ops = [op for op in ops if op.__class__.__name__ == "AlterColumn"]
        assert len(alter_ops) == 1
        assert alter_ops[0].column_name == "id"
        assert alter_ops[0].autoincrement is True
        assert alter_ops[0].old_autoincrement is None

    def test_diff_states_detects_autoincrement_added(self) -> None:
        from openviper.db.migrations.writer import diff_states

        old_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": True,
                    },
                    {"name": "name", "type": "TEXT", "nullable": True},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        new_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": True,
                        "autoincrement": True,
                    },
                    {"name": "name", "type": "TEXT", "nullable": True},
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        ops = diff_states(new_state, old_state)
        alter_ops = [op for op in ops if op.__class__.__name__ == "AlterColumn"]
        assert len(alter_ops) == 1
        assert alter_ops[0].autoincrement is True
        assert alter_ops[0].old_autoincrement is None

    def test_diff_states_detects_primary_key_change(self) -> None:
        from openviper.db.migrations.writer import diff_states

        old_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": True,
                        "autoincrement": True,
                    },
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        new_state = {
            "my_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "field_class": "IntegerField",
                        "nullable": False,
                        "primary_key": False,
                        "autoincrement": True,
                    },
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        ops = diff_states(new_state, old_state)
        alter_ops = [op for op in ops if op.__class__.__name__ == "AlterColumn"]
        assert len(alter_ops) == 1
        assert alter_ops[0].primary_key is False
        assert alter_ops[0].old_primary_key is True

    def test_format_operation_alter_column_includes_autoincrement(self) -> None:
        from openviper.db.migrations.executor import AlterColumn

        op = AlterColumn(
            table_name="my_table",
            column_name="id",
            column_type="INTEGER",
            autoincrement=True,
            old_autoincrement=False,
        )
        formatted = format_operation(op)
        assert "autoincrement=True" in formatted
        assert "old_autoincrement=False" in formatted

    def test_format_operation_alter_column_includes_primary_key(self) -> None:
        from openviper.db.migrations.executor import AlterColumn

        op = AlterColumn(
            table_name="my_table",
            column_name="id",
            column_type="INTEGER",
            primary_key=True,
            old_primary_key=False,
        )
        formatted = format_operation(op)
        assert "primary_key=True" in formatted
        assert "old_primary_key=False" in formatted
