"""Unit tests for JSON schema file reading and writing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import orjson
import pytest

from openviper.db.schemas.json_reader import (
    read_all_json_schemas,
    read_all_raw_schemas,
    read_json_schema,
    schema_to_state,
)
from openviper.db.schemas.json_writer import delete_json_schema, write_json_schema

SAMPLE_SCHEMA: dict[str, Any] = {
    "model": "TestModel",
    "app": "testapp",
    "table_name": "testapp_testmodel",
    "last_modified": "2026-06-20T10:00:00Z",
    "columns": [
        {
            "name": "id",
            "type": "INTEGER",
            "nullable": False,
            "primary_key": True,
            "autoincrement": True,
            "default": None,
        },
        {"name": "title", "type": "VARCHAR(200)", "nullable": False, "default": None},
    ],
    "indexes": [{"name": "idx_testapp_testmodel_title", "fields": ["title"]}],
    "unique_together": [],
}


class TestReadJsonSchema:
    """Tests for read_json_schema function."""

    def test_read_existing_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "TestModel.json"
        path.write_bytes(orjson.dumps(SAMPLE_SCHEMA))
        result = read_json_schema(str(tmp_path), "TestModel")
        assert result is not None
        assert result["model"] == "TestModel"
        assert result["table_name"] == "testapp_testmodel"

    def test_read_nonexistent_schema_returns_none(self, tmp_path: Path) -> None:
        result = read_json_schema(str(tmp_path), "Nonexistent")
        assert result is None


class TestSchemaToState:
    """Tests for schema_to_state conversion."""

    def test_converts_schema_to_state_dict(self) -> None:
        state = schema_to_state(SAMPLE_SCHEMA)
        assert "testapp_testmodel" in state
        table = state["testapp_testmodel"]
        assert "columns" in table
        assert "indexes" in table
        assert "unique_together" in table
        assert len(table["columns"]) == 2
        assert table["columns"][0]["name"] == "id"

    def test_state_excludes_metadata_keys(self) -> None:
        state = schema_to_state(SAMPLE_SCHEMA)
        table = state["testapp_testmodel"]
        assert "model" not in table
        assert "app" not in table
        assert "last_modified" not in table


class TestReadAllJsonSchemas:
    """Tests for read_all_json_schemas function."""

    def test_reads_multiple_schemas(self, tmp_path: Path) -> None:
        schema1 = {**SAMPLE_SCHEMA, "table_name": "table_a"}
        schema2 = {**SAMPLE_SCHEMA, "model": "ModelB", "table_name": "table_b"}
        (tmp_path / "ModelA.json").write_bytes(orjson.dumps(schema1))
        (tmp_path / "ModelB.json").write_bytes(orjson.dumps(schema2))
        state = read_all_json_schemas(str(tmp_path))
        assert "table_a" in state
        assert "table_b" in state

    def test_empty_dir_returns_empty_dict(self, tmp_path: Path) -> None:
        state = read_all_json_schemas(str(tmp_path))
        assert state == {}

    def test_nonexistent_dir_returns_empty_dict(self, tmp_path: Path) -> None:
        state = read_all_json_schemas(str(tmp_path / "nonexistent"))
        assert state == {}


class TestReadAllRawSchemas:
    """Tests for read_all_raw_schemas function."""

    def test_preserves_full_schema_dict(self, tmp_path: Path) -> None:
        (tmp_path / "TestModel.json").write_bytes(orjson.dumps(SAMPLE_SCHEMA))
        result = read_all_raw_schemas(str(tmp_path))
        assert "testapp_testmodel" in result
        assert result["testapp_testmodel"]["model"] == "TestModel"
        assert result["testapp_testmodel"]["app"] == "testapp"


class TestDeleteJsonSchema:
    """Tests for delete_json_schema function."""

    def test_deletes_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "TestModel.json"
        path.write_bytes(orjson.dumps(SAMPLE_SCHEMA))
        assert delete_json_schema(str(tmp_path), "TestModel") is True
        assert not path.exists()

    def test_returns_false_for_nonexistent(self, tmp_path: Path) -> None:
        assert delete_json_schema(str(tmp_path), "Nonexistent") is False
