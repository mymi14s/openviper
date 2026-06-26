"""Unit tests for Meta option tracking in the JSON schema pipeline.

Covers unique_together, index_together, constraints (CheckConstraint,
UniqueConstraint), single, managed, db_index, and unique field-level
property tracking through build_schema_dict, detect_column_changes,
diff_states, and schema_to_state.
"""

from __future__ import annotations

import typing as t
from unittest.mock import MagicMock

import pytest

from openviper.db.fields import CheckConstraint, UniqueConstraint
from openviper.db.migrations.executor import (
    AddConstraint,
    AlterColumn,
    CreateIndex,
    CreateTable,
    RemoveConstraint,
)
from openviper.db.migrations.writer import diff_states, model_state_snapshot, normalize_state
from openviper.db.schemas.detect import (
    build_model_constraints,
    build_model_index_together,
    build_model_unique_together,
    detect_column_changes,
)
from openviper.db.schemas.json_reader import schema_to_state
from openviper.db.schemas.json_writer import build_schema_dict


def make_mock_field(
    name: str,
    *,
    column_type: str = "VARCHAR(255)",
    nullable: bool = True,
    primary_key: bool = False,
    auto_increment: bool = False,
    unique: bool = False,
    db_index: bool = False,
    default: t.Any = None,
) -> MagicMock:
    """Create a mock field object."""
    field = MagicMock()
    field.name = name
    field.column_name = name
    field.column_type = column_type
    field.null = nullable
    field.primary_key = primary_key
    field.auto_increment = auto_increment
    field.unique = unique
    field.db_index = db_index
    field.default = default
    return field


def make_mock_model(
    table_name: str = "testapp_model",
    fields: dict[str, MagicMock] | None = None,
    *,
    meta_indexes: list[t.Any] | None = None,
    meta_unique_together: list[list[str]] | None = None,
    meta_index_together: list[list[str]] | None = None,
    meta_constraints: list[t.Any] | None = None,
    is_single: bool = False,
    is_managed: bool = True,
    is_virtual: bool = False,
    is_abstract: bool = False,
) -> MagicMock:
    """Create a mock model class with all Meta attributes."""
    if fields is None:
        fields = {
            "id": make_mock_field(
                "id",
                column_type="INTEGER",
                nullable=False,
                primary_key=True,
                auto_increment=True,
            ),
            "name": make_mock_field("name", column_type="VARCHAR(255)", nullable=False),
        }

    model = MagicMock()
    model.__name__ = table_name.title().replace("_", "")
    model._table_name = table_name
    model._fields = fields
    model._meta_indexes = meta_indexes or []
    model._meta_unique_together = meta_unique_together or []
    model._meta_index_together = meta_index_together or []
    model._meta_constraints = meta_constraints or []
    model._is_single = is_single
    model._is_managed = is_managed
    model._meta = MagicMock()
    model._meta.virtual = is_virtual
    model.Meta = MagicMock()
    model.Meta.abstract = is_abstract
    return model


class TestBuildSchemaDictMetaTracking:
    """Tests for build_schema_dict Meta serialization."""

    def test_unique_together_is_serialized(self) -> None:
        model = make_mock_model(
            meta_unique_together=[["name", "email"]],
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert "unique_together" in schema
        assert schema["unique_together"] == [["email", "name"]]

    def test_index_together_is_serialized(self) -> None:
        model = make_mock_model(
            meta_index_together=[["name", "email"]],
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert "index_together" in schema
        assert schema["index_together"] == [["email", "name"]]

    def test_constraints_check_is_serialized(self) -> None:
        constraint = CheckConstraint(name="price_positive", check="price > 0")
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "price": make_mock_field("price", column_type="INTEGER", nullable=False),
            },
            meta_constraints=[constraint],
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert "constraints" in schema
        assert len(schema["constraints"]) == 1
        assert schema["constraints"][0]["name"] == "price_positive"
        assert schema["constraints"][0]["type"] == "CHECK"
        assert schema["constraints"][0]["check"] == "price > 0"

    def test_constraints_unique_is_serialized(self) -> None:
        constraint = UniqueConstraint(
            fields=["slug"], name="unique_published_slug", condition="published = 1"
        )
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "slug": make_mock_field("slug", column_type="VARCHAR(255)", nullable=False),
            },
            meta_constraints=[constraint],
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert "constraints" in schema
        assert len(schema["constraints"]) == 1
        assert schema["constraints"][0]["name"] == "unique_published_slug"
        assert schema["constraints"][0]["type"] == "UNIQUE"
        assert schema["constraints"][0]["fields"] == ["slug"]
        assert schema["constraints"][0]["condition"] == "published = 1"

    def test_single_is_serialized(self) -> None:
        model = make_mock_model(is_single=True)
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert schema["single"] is True

    def test_single_defaults_to_false(self) -> None:
        model = make_mock_model()
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert schema["single"] is False

    def test_managed_is_serialized(self) -> None:
        model = make_mock_model(is_managed=True)
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        assert schema["managed"] is True

    def test_managed_false_returns_none(self) -> None:
        model = make_mock_model(is_managed=False)
        schema = build_schema_dict(model, "testapp")
        assert schema is None

    def test_db_index_generates_index_entry(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "country": make_mock_field(
                    "country", column_type="CHAR(2)", nullable=True, db_index=True
                ),
            },
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        index_names = [i["name"] for i in schema["indexes"]]
        assert "idx_testapp_model_country" in index_names

    def test_unique_field_does_not_generate_separate_index(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "email": make_mock_field(
                    "email", column_type="VARCHAR(254)", nullable=False, unique=True
                ),
            },
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        index_names = [i["name"] for i in schema["indexes"]]
        assert "idx_testapp_model_email" not in index_names

    def test_unique_field_is_serialized_in_column(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "email": make_mock_field(
                    "email", column_type="VARCHAR(254)", nullable=False, unique=True
                ),
            },
        )
        schema = build_schema_dict(model, "testapp")
        assert schema is not None
        email_col = [c for c in schema["columns"] if c["name"] == "email"][0]
        assert email_col["unique"] is True


class TestDetectColumnChangesMetaTracking:
    """Tests for detect_column_changes Meta comparison."""

    def test_detects_unique_together_added(self) -> None:
        model = make_mock_model(
            meta_unique_together=[["name", "email"]],
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(255)", "nullable": False, "default": None},
                {"name": "email", "type": "VARCHAR(254)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("unique_together_changed") is True

    def test_detects_unique_together_removed(self) -> None:
        model = make_mock_model()
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(255)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [["name", "id"]],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("unique_together_changed") is True

    def test_no_change_when_unique_together_matches(self) -> None:
        model = make_mock_model(
            meta_unique_together=[["id", "name"]],
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(255)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [["id", "name"]],
        }
        changes = detect_column_changes(model, json_state)
        assert "unique_together_changed" not in changes

    def test_detects_index_together_added(self) -> None:
        model = make_mock_model(
            meta_index_together=[["name", "email"]],
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(255)", "nullable": False, "default": None},
                {"name": "email", "type": "VARCHAR(254)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
            "index_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("index_together_changed") is True

    def test_detects_index_together_removed(self) -> None:
        model = make_mock_model()
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(255)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
            "index_together": [["id", "name"]],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("index_together_changed") is True

    def test_detects_constraints_changed(self) -> None:
        constraint = CheckConstraint(name="price_positive", check="price > 0")
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "price": make_mock_field("price", column_type="INTEGER", nullable=False),
            },
            meta_constraints=[constraint],
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "price", "type": "INTEGER", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
            "constraints": [],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("constraints_changed") is True

    def test_detects_db_index_added_to_existing_field(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "country": make_mock_field(
                    "country", column_type="CHAR(2)", nullable=True, db_index=True
                ),
            },
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "country", "type": "CHAR(2)", "nullable": True, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert changes.get("indexes_changed") is True

    def test_detects_unique_added_to_existing_field(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "email": make_mock_field(
                    "email", column_type="VARCHAR(254)", nullable=False, unique=True
                ),
            },
        )
        json_state = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "email", "type": "VARCHAR(254)", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert "altered" in changes
        assert len(changes["altered"]) == 1
        assert changes["altered"][0]["name"] == "email"


class TestDiffStatesMetaTracking:
    """Tests for diff_states Meta operation generation."""

    def test_create_table_includes_unique_together(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [["name", "id"]],
                "index_together": [],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        ops = diff_states(current, {})
        create_ops = [op for op in ops if isinstance(op, CreateTable)]
        assert len(create_ops) == 1
        assert create_ops[0].unique_together == [["name", "id"]]

    def test_create_table_includes_index_together(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [["name", "id"]],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        ops = diff_states(current, {})
        create_ops = [op for op in ops if isinstance(op, CreateTable)]
        assert len(create_ops) == 1
        assert create_ops[0].index_together == [["name", "id"]]

    def test_create_table_includes_constraints(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "price", "type": "INTEGER", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [
                    {"name": "price_positive", "type": "CHECK", "check": "price > 0"},
                ],
                "single": False,
                "managed": True,
            }
        }
        ops = diff_states(current, {})
        create_ops = [op for op in ops if isinstance(op, CreateTable)]
        assert len(create_ops) == 1
        assert len(create_ops[0].constraints) == 1
        assert create_ops[0].constraints[0]["name"] == "price_positive"

    def test_create_table_includes_single(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
                "single": True,
                "managed": True,
            }
        }
        ops = diff_states(current, {})
        create_ops = [op for op in ops if isinstance(op, CreateTable)]
        assert len(create_ops) == 1
        assert create_ops[0].single is True

    def test_diff_detects_unique_together_added_on_existing_table(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [["email", "name"]],
                "index_together": [],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
            }
        }
        ops = diff_states(current, existing)
        create_index_ops = [op for op in ops if isinstance(op, CreateIndex)]
        unique_indexes = [op for op in create_index_ops if op.unique]
        assert len(unique_indexes) == 1
        assert unique_indexes[0].index_name == "uniq_test_table_email_name"

    def test_diff_detects_index_together_added_on_existing_table(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [["email", "name"]],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
            }
        }
        ops = diff_states(current, existing)
        create_index_ops = [op for op in ops if isinstance(op, CreateIndex)]
        non_unique_indexes = [op for op in create_index_ops if not op.unique]
        assert len(non_unique_indexes) == 1
        assert non_unique_indexes[0].index_name == "idx_test_table_email_name"

    def test_diff_detects_constraint_added_on_existing_table(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "price", "type": "INTEGER", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [
                    {"name": "price_positive", "type": "CHECK", "check": "price > 0"},
                ],
                "single": False,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "price", "type": "INTEGER", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
            }
        }
        ops = diff_states(current, existing)
        add_constraint_ops = [op for op in ops if isinstance(op, AddConstraint)]
        assert len(add_constraint_ops) == 1
        assert add_constraint_ops[0].constraint_name == "price_positive"
        assert add_constraint_ops[0].constraint_type == "CHECK"

    def test_diff_detects_constraint_removed_on_existing_table(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "price", "type": "INTEGER", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "price", "type": "INTEGER", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [
                    {"name": "price_positive", "type": "CHECK", "check": "price > 0"},
                ],
            }
        }
        ops = diff_states(current, existing)
        remove_ops = [op for op in ops if isinstance(op, RemoveConstraint)]
        assert len(remove_ops) == 1
        assert remove_ops[0].constraint_name == "price_positive"

    def test_diff_detects_single_added_on_existing_table(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
                "single": True,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
                "single": False,
            }
        }
        ops = diff_states(current, existing)
        add_ops = [op for op in ops if isinstance(op, AddConstraint)]
        single_ops = [op for op in add_ops if op.constraint_type == "CHECK"]
        assert len(single_ops) == 1
        assert single_ops[0].constraint_name == "chk_test_table_single_row"

    def test_diff_detects_unique_change_on_existing_column(self) -> None:
        current = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False, "unique": True},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
                "single": False,
                "managed": True,
            }
        }
        existing = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                    {"name": "email", "type": "VARCHAR(254)", "nullable": False},
                ],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [],
            }
        }
        ops = diff_states(current, existing)
        alter_ops = [op for op in ops if isinstance(op, AlterColumn)]
        assert len(alter_ops) == 1
        assert alter_ops[0].unique is True


class TestSchemaToStateMetaTracking:
    """Tests for schema_to_state Meta conversion."""

    def test_includes_constraints_key(self) -> None:
        schema = {
            "model": "TestModel",
            "app": "testapp",
            "table_name": "testapp_testmodel",
            "columns": [],
            "indexes": [],
            "unique_together": [],
            "index_together": [],
            "constraints": [{"name": "ck1", "type": "CHECK", "check": "x > 0"}],
            "single": False,
            "managed": True,
        }
        state = schema_to_state(schema)
        table = state["testapp_testmodel"]
        assert "constraints" in table
        assert len(table["constraints"]) == 1

    def test_includes_index_together_key(self) -> None:
        schema = {
            "model": "TestModel",
            "app": "testapp",
            "table_name": "testapp_testmodel",
            "columns": [],
            "indexes": [],
            "unique_together": [],
            "index_together": [["a", "b"]],
            "constraints": [],
            "single": False,
            "managed": True,
        }
        state = schema_to_state(schema)
        table = state["testapp_testmodel"]
        assert "index_together" in table
        assert table["index_together"] == [["a", "b"]]

    def test_skips_unmanaged_model(self) -> None:
        schema = {
            "model": "TestModel",
            "app": "testapp",
            "table_name": "testapp_testmodel",
            "columns": [],
            "indexes": [],
            "unique_together": [],
            "index_together": [],
            "constraints": [],
            "single": False,
            "managed": False,
        }
        state = schema_to_state(schema)
        assert state == {}


class TestNormalizeStateMetaTracking:
    """Tests for normalize_state with Meta fields."""

    def test_normalizes_index_together(self) -> None:
        state = {
            "test_table": {
                "columns": [],
                "indexes": [],
                "unique_together": [],
                "index_together": [["b", "a"], ["d", "c"]],
                "constraints": [],
            }
        }
        result = normalize_state(state)
        assert result["test_table"]["index_together"] == [["a", "b"], ["c", "d"]]

    def test_strips_constraint_condition_and_check(self) -> None:
        state = {
            "test_table": {
                "columns": [],
                "indexes": [],
                "unique_together": [],
                "index_together": [],
                "constraints": [
                    {"name": "ck1", "type": "CHECK", "check": "x > 0"},
                    {"name": "uq1", "type": "UNIQUE", "fields": ["a"], "condition": "x = 1"},
                ],
            }
        }
        result = normalize_state(state)
        for c in result["test_table"]["constraints"]:
            assert "condition" not in c
            assert "check" not in c


class TestBuildModelHelpers:
    """Tests for build_model_* helper functions."""

    def test_build_model_unique_together_returns_sorted(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "name": make_mock_field("name", column_type="VARCHAR(255)", nullable=False),
                "email": make_mock_field("email", column_type="VARCHAR(254)", nullable=False),
            },
            meta_unique_together=[["name", "email"]],
        )
        result = build_model_unique_together(model)
        assert result == [["email", "name"]]

    def test_build_model_index_together_returns_sorted(self) -> None:
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "name": make_mock_field("name", column_type="VARCHAR(255)", nullable=False),
                "email": make_mock_field("email", column_type="VARCHAR(254)", nullable=False),
            },
            meta_index_together=[["name", "email"]],
        )
        result = build_model_index_together(model)
        assert result == [["email", "name"]]

    def test_build_model_constraints_check(self) -> None:
        constraint = CheckConstraint(name="ck1", check="x > 0")
        model = make_mock_model(meta_constraints=[constraint])
        result = build_model_constraints(model)
        assert len(result) == 1
        assert result[0]["name"] == "ck1"
        assert result[0]["type"] == "CHECK"
        assert result[0]["check"] == "x > 0"

    def test_build_model_constraints_unique(self) -> None:
        constraint = UniqueConstraint(fields=["slug"], name="uq1")
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "slug": make_mock_field("slug", column_type="VARCHAR(255)", nullable=False),
            },
            meta_constraints=[constraint],
        )
        result = build_model_constraints(model)
        assert len(result) == 1
        assert result[0]["name"] == "uq1"
        assert result[0]["type"] == "UNIQUE"
        assert result[0]["fields"] == ["slug"]

    def test_build_model_constraints_unique_with_condition(self) -> None:
        constraint = UniqueConstraint(fields=["slug"], name="uq1", condition="published = 1")
        model = make_mock_model(
            fields={
                "id": make_mock_field("id", column_type="INTEGER", nullable=False,
                    primary_key=True),
                "slug": make_mock_field("slug", column_type="VARCHAR(255)", nullable=False),
            },
            meta_constraints=[constraint],
        )
        result = build_model_constraints(model)
        assert result[0]["condition"] == "published = 1"

    def test_build_model_constraints_empty(self) -> None:
        model = make_mock_model()
        result = build_model_constraints(model)
        assert result == []
