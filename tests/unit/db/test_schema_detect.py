"""Unit tests for schema change detection logic."""

from __future__ import annotations

import typing as t
from unittest.mock import MagicMock

import pytest

from openviper.db.schemas.detect import (
    detect_changes,
    detect_column_changes,
    match_renames,
    types_match,
)
from openviper.exceptions import MigrationError


def make_mock_model(
    table_name: str,
    fields: dict[str, dict[str, t.Any]],
) -> MagicMock:
    """Create a mock model class with _fields and _table_name."""
    mock_fields = {}
    for name, attrs in fields.items():
        field = MagicMock()
        field.column_name = name
        field.column_type = attrs.get("type", "VARCHAR(255)")
        field.null = attrs.get("nullable", True)
        field.primary_key = attrs.get("primary_key", False)
        field.auto_increment = attrs.get("autoincrement", False)
        field.unique = attrs.get("unique", False)
        field.default = attrs.get("default")
        field.db_index = attrs.get("db_index", False)
        mock_fields[name] = field

    model = MagicMock()
    model.__name__ = table_name.title().replace("_", "")
    model._table_name = table_name
    model._fields = mock_fields
    model._meta_indexes = []
    model._meta_unique_together = []
    model._meta = None
    model.Meta = None
    return model


class TestTypesMatch:
    """Tests for types_match function."""

    def test_same_base_type_matches(self) -> None:
        assert types_match("VARCHAR(200)", "VARCHAR(100)") is True

    def test_different_base_types_dont_match(self) -> None:
        assert types_match("INTEGER", "VARCHAR(255)") is False

    def test_case_insensitive(self) -> None:
        assert types_match("integer", "INTEGER") is True

    def test_strips_length_suffix(self) -> None:
        assert types_match("TEXT", "TEXT") is True
        assert types_match("VARCHAR(50)", "VARCHAR(200)") is True


class TestMatchRenames:
    """Tests for match_renames function."""

    def test_matches_by_type(self) -> None:
        orphaned_json = {"old_name": {"type": "VARCHAR(255)"}}
        orphaned_model = {"new_name": {"type": "VARCHAR(100)"}}
        result = match_renames(orphaned_json, orphaned_model)
        assert result == {"new_name": "old_name"}

    def test_no_match_when_types_differ(self) -> None:
        orphaned_json = {"old_name": {"type": "INTEGER"}}
        orphaned_model = {"new_name": {"type": "VARCHAR(255)"}}
        result = match_renames(orphaned_json, orphaned_model)
        assert result == {}

    def test_multiple_renames(self) -> None:
        orphaned_json = {
            "old_a": {"type": "VARCHAR(255)"},
            "old_b": {"type": "INTEGER"},
        }
        orphaned_model = {
            "new_a": {"type": "VARCHAR(100)"},
            "new_b": {"type": "INTEGER"},
        }
        result = match_renames(orphaned_json, orphaned_model)
        assert result == {"new_a": "old_a", "new_b": "old_b"}

    def test_empty_inputs(self) -> None:
        assert match_renames({}, {}) == {}


class TestDetectChanges:
    """Tests for detect_changes function."""

    def test_detects_new_model(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "title": {"type": "VARCHAR(200)", "nullable": False},
            },
        )
        report = detect_changes([model], {}, "blog")
        assert len(report["created"]) == 1
        assert report["created"][0] is model
        assert report["updated"] == []
        assert report["deleted"] == []

    def test_detects_deleted_model(self) -> None:
        json_state = {
            "blog_post": {
                "columns": [{"name": "id", "type": "INTEGER", "nullable": False}],
                "indexes": [],
                "unique_together": [],
            }
        }
        report = detect_changes([], json_state, "blog")
        assert report["deleted"] == ["blog_post"]
        assert report["created"] == []

    def test_detects_unchanged_model(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
            },
        )
        json_state = {
            "blog_post": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "nullable": False,
                        "primary_key": True,
                        "autoincrement": True,
                        "default": None,
                    },
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        report = detect_changes([model], json_state, "blog")
        assert report["created"] == []
        assert report["updated"] == []
        assert "blog_post" not in report["deleted"]
        assert "BlogPost" in report["unchanged"]


class TestDetectColumnChanges:
    """Tests for detect_column_changes function."""

    def test_detects_added_column(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "title": {"type": "VARCHAR(200)", "nullable": False},
                "body": {"type": "TEXT", "nullable": True},
            },
        )
        json_state = {
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
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert "added" in changes
        assert len(changes["added"]) == 1
        assert changes["added"][0]["name"] == "body"

    def test_detects_removed_column(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
            },
        )
        json_state = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                    "autoincrement": True,
                    "default": None,
                },
                {"name": "legacy_field", "type": "VARCHAR(100)", "nullable": True, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert "removed" in changes
        assert len(changes["removed"]) == 1
        assert changes["removed"][0]["name"] == "legacy_field"

    def test_detects_renamed_column(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "content": {"type": "TEXT", "nullable": True},
            },
        )
        json_state = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                    "autoincrement": True,
                    "default": None,
                },
                {"name": "body", "type": "TEXT", "nullable": True, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert "renamed" in changes
        assert len(changes["renamed"]) == 1
        assert changes["renamed"][0]["new_name"] == "content"
        assert changes["renamed"][0]["old_name"] == "body"

    def test_detects_altered_column_type(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "title": {"type": "VARCHAR(500)", "nullable": False},
            },
        )
        json_state = {
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
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert "altered" in changes
        assert len(changes["altered"]) == 1
        assert changes["altered"][0]["name"] == "title"

    def test_rejects_incompatible_type_change(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "view_count": {"type": "VARCHAR(50)", "nullable": False},
            },
        )
        json_state = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                    "autoincrement": True,
                    "default": None,
                },
                {"name": "view_count", "type": "INTEGER", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        with pytest.raises(MigrationError, match="Cannot change column type"):
            detect_column_changes(model, json_state)

    def test_force_allows_incompatible_type_change(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "view_count": {"type": "VARCHAR(50)", "nullable": False},
            },
        )
        json_state = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                    "autoincrement": True,
                    "default": None,
                },
                {"name": "view_count", "type": "INTEGER", "nullable": False, "default": None},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state, force=True)
        assert "altered" in changes
        assert len(changes["altered"]) == 1

    def test_no_changes_returns_empty_dict(self) -> None:
        model = make_mock_model(
            "blog_post",
            {
                "id": {
                    "type": "INTEGER",
                    "primary_key": True,
                    "autoincrement": True,
                    "nullable": False,
                },
                "title": {"type": "VARCHAR(200)", "nullable": False},
            },
        )
        json_state = {
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
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(model, json_state)
        assert changes == {}
