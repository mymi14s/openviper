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
    _format_columns,
    _format_operation,
    next_migration_number,
    write_initial_migration,
)


class _DummyField:
    def __init__(
        self,
        *,
        column_name: str,
        column_type: str,
        null: bool = True,
        primary_key: bool = False,
        auto_increment: bool = False,
        unique: bool = False,
        default=None,
    ) -> None:
        self.column_name = column_name
        self._column_type = column_type
        self.null = null
        self.primary_key = primary_key
        self.auto_increment = auto_increment
        self.unique = unique
        self.default = default


def test_format_columns_rejects_invalid_column_identifier() -> None:
    class BadModel:
        __name__ = "BadModel"
        _fields = {"bad": _DummyField(column_name="bad-name", column_type="TEXT")}

    with pytest.raises(ValueError, match="Invalid column name"):
        _format_columns(BadModel)


def test_format_columns_rejects_invalid_fk_target_table_identifier() -> None:
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
            _format_columns(FKModel)


def test_write_initial_migration_includes_unique_together_indexes(tmp_path: Path) -> None:
    class ModelWithUniqueTogether:
        __name__ = "ModelWithUniqueTogether"
        _table_name = "things"
        _meta_indexes: list = []
        _meta_unique_together = [("a", "b")]
        _fields = {
            "id": _DummyField(
                column_name="id",
                column_type="INTEGER",
                null=False,
                primary_key=True,
                auto_increment=True,
            ),
            "a": _DummyField(column_name="a", column_type="TEXT"),
            "b": _DummyField(column_name="b", column_type="TEXT"),
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


def test_next_migration_number_ignores_non_numeric_prefixes(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    (mig_dir / "abcd_not_a_number.py").write_text("# noop\n")
    assert next_migration_number(str(mig_dir)) == "0001"


def test_format_operation_fallback_for_unknown_operation() -> None:
    class Unknown(Operation):
        pass

    formatted = _format_operation(Unknown())
    assert "Unsupported operation" in formatted
