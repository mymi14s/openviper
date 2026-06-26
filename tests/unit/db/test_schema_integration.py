"""Integration tests for the JSON schema migration system.

Tests the full flow: makemigrations generates JSON schemas,
migrate applies them to a database, and subsequent runs are
idempotent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import orjson
import pytest
import sqlalchemy as sa

from openviper.core.management.commands.makemigrations import Command as MakemigrationsCommand
from openviper.core.management.commands.migrate import Command as MigrateCommand
from openviper.db.migrations.executor import (
    AddColumn,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    RemoveColumn,
    RemoveIndex,
    RenameColumn,
)
from openviper.db.migrations.writer import normalize_state
from openviper.db.schemas.detect import clean_change_metadata
from openviper.db.schemas.introspect import introspect_table_sync
from openviper.db.schemas.json_reader import read_all_json_schemas, read_all_raw_schemas
from openviper.db.schemas.sync import SchemaSync

SAMPLE_SCHEMA_A: dict[str, Any] = {
    "model": "ModelA",
    "app": "testapp",
    "table_name": "testapp_modela",
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
    "indexes": [{"name": "idx_testapp_modela_title", "fields": ["title"]}],
    "unique_together": [],
}

SAMPLE_SCHEMA_B: dict[str, Any] = {
    "model": "ModelB",
    "app": "testapp",
    "table_name": "testapp_modelb",
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
        {"name": "body", "type": "TEXT", "nullable": True, "default": None},
    ],
    "indexes": [],
    "unique_together": [],
}


class TestJsonSchemaRoundTrip:
    """Test writing and reading JSON schema files."""

    def test_write_and_read_schema(self, tmp_path: Path) -> None:
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        path = schemas_dir / "ModelA.json"
        path.write_bytes(orjson.dumps(SAMPLE_SCHEMA_A, option=orjson.OPT_INDENT_2))

        state = read_all_json_schemas(str(schemas_dir))
        assert "testapp_modela" in state
        assert len(state["testapp_modela"]["columns"]) == 2

    def test_read_raw_preserves_metadata(self, tmp_path: Path) -> None:
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "ModelA.json").write_bytes(orjson.dumps(SAMPLE_SCHEMA_A))

        raw = read_all_raw_schemas(str(schemas_dir))
        assert "testapp_modela" in raw
        assert raw["testapp_modela"]["model"] == "ModelA"
        assert raw["testapp_modela"]["app"] == "testapp"


class TestCleanChangeMetadata:
    """Test that clean_change_metadata strips transient fields."""

    def test_removes_old_name(self) -> None:
        schema = {
            "columns": [
                {"name": "content", "type": "TEXT", "old_name": "body", "changed_at": "2026-01-01"},
            ],
        }
        cleaned = clean_change_metadata(schema)
        assert "old_name" not in cleaned["columns"][0]
        assert "changed_at" not in cleaned["columns"][0]

    def test_removes_old_type(self) -> None:
        schema = {
            "columns": [
                {
                    "name": "title",
                    "type": "VARCHAR(500)",
                    "old_type": "VARCHAR(200)",
                    "changed_at": "2026-01-01",
                },
            ],
        }
        cleaned = clean_change_metadata(schema)
        assert "old_type" not in cleaned["columns"][0]

    def test_preserves_normal_columns(self) -> None:
        schema = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False},
            ],
        }
        cleaned = clean_change_metadata(schema)
        assert cleaned["columns"][0]["name"] == "id"
        assert cleaned["columns"][0]["type"] == "INTEGER"


class TestNormalizeState:
    """Test that normalize_state strips unreliable fields for comparison."""

    def test_preserves_autoincrement(self) -> None:
        state = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER", "autoincrement": True}],
                "indexes": [],
                "unique_together": [],
            }
        }
        normalized = normalize_state(state)
        assert normalized["t"]["columns"][0].get("autoincrement") is True

    def test_strips_unique(self) -> None:
        state = {
            "t": {
                "columns": [{"name": "email", "type": "VARCHAR(255)", "unique": True}],
                "indexes": [],
                "unique_together": [],
            }
        }
        normalized = normalize_state(state)
        assert "unique" not in normalized["t"]["columns"][0]

    def test_strips_default(self) -> None:
        state = {
            "t": {
                "columns": [{"name": "active", "type": "BOOLEAN", "default": True}],
                "indexes": [],
                "unique_together": [],
            }
        }
        normalized = normalize_state(state)
        assert "default" not in normalized["t"]["columns"][0]

    def test_strips_nullable(self) -> None:
        state = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER", "nullable": False}],
                "indexes": [],
                "unique_together": [],
            }
        }
        normalized = normalize_state(state)
        assert "nullable" not in normalized["t"]["columns"][0]

    def test_normalizes_boolean_to_integer(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "active", "type": "BOOLEAN"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "active", "type": "INTEGER"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_uuid_to_text(self) -> None:
        state_a = {
            "t": {"columns": [{"name": "id", "type": "UUID"}], "indexes": [], "unique_together": []}
        }
        state_b = {
            "t": {"columns": [{"name": "id", "type": "TEXT"}], "indexes": [], "unique_together": []}
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_varchar_to_text(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "name", "type": "VARCHAR(20)"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "name", "type": "TEXT"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_timestamp_to_datetime(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "created", "type": "TIMESTAMP"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "created", "type": "DATETIME"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_timestamp_without_tz_to_datetime(self) -> None:
        """PostgreSQL returns TIMESTAMP WITHOUT TIME ZONE for datetime columns."""
        state_a = {
            "t": {
                "columns": [{"name": "created", "type": "TIMESTAMP WITHOUT TIME ZONE"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "created", "type": "DATETIME"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_timestamp_with_tz_to_datetime(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "created", "type": "TIMESTAMP WITH TIME ZONE"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "created", "type": "DATETIME"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_int_to_integer(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "count", "type": "INT"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "count", "type": "INTEGER"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_normalizes_nvarchar2_to_text(self) -> None:
        state_a = {
            "t": {
                "columns": [{"name": "name", "type": "NVARCHAR2(100)"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [{"name": "name", "type": "TEXT"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)

    def test_removes_single_column_unique_constraints(self) -> None:
        """Single-column UNIQUE constraints are redundant with column unique attr."""
        state = {
            "users": {
                "columns": [
                    {"name": "id", "type": "INTEGER"},
                    {"name": "email", "type": "TEXT", "unique": True},
                ],
                "indexes": [],
                "unique_together": [],
                "constraints": [
                    {
                        "name": "uniq_users_email",
                        "type": "UNIQUE",
                        "fields": ["email"],
                    }
                ],
            }
        }
        normalized = normalize_state(state)
        constraints = normalized["users"]["constraints"]
        assert len(constraints) == 0

    def test_preserves_multi_column_unique_constraints(self) -> None:
        """Multi-column UNIQUE constraints must be preserved during normalization."""
        state = {
            "users": {
                "columns": [
                    {"name": "id", "type": "INTEGER"},
                    {"name": "first_name", "type": "TEXT"},
                    {"name": "last_name", "type": "TEXT"},
                ],
                "indexes": [],
                "unique_together": [],
                "constraints": [
                    {
                        "name": "uniq_users_name",
                        "type": "UNIQUE",
                        "fields": ["first_name", "last_name"],
                    }
                ],
            }
        }
        normalized = normalize_state(state)
        constraints = normalized["users"]["constraints"]
        assert len(constraints) == 1
        assert constraints[0]["fields"] == ["first_name", "last_name"]

    def test_preserves_check_constraints(self) -> None:
        """CHECK constraints must be preserved during normalization."""
        state = {
            "orders": {
                "columns": [
                    {"name": "id", "type": "INTEGER"},
                    {"name": "quantity", "type": "INTEGER"},
                ],
                "indexes": [],
                "unique_together": [],
                "constraints": [
                    {
                        "name": "chk_orders_quantity",
                        "type": "CHECK",
                        "check": "quantity > 0",
                    }
                ],
            }
        }
        normalized = normalize_state(state)
        constraints = normalized["orders"]["constraints"]
        assert len(constraints) == 1
        assert constraints[0]["type"] == "CHECK"

    def test_preserves_primary_key(self) -> None:
        state = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
                "indexes": [],
                "unique_together": [],
            }
        }
        normalized = normalize_state(state)
        assert normalized["t"]["columns"][0]["primary_key"] is True

    def test_equal_states_with_different_unreliable_fields(self) -> None:
        state_a = {
            "t": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "autoincrement": True,
                        "nullable": False,
                        "default": None,
                        "unique": False,
                    }
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        state_b = {
            "t": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "autoincrement": True}
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        assert normalize_state(state_a) == normalize_state(state_b)


class TestSchemaSyncIdempotency:
    """Test that SchemaSync.sync is idempotent."""

    @pytest.mark.asyncio
    async def test_sync_with_no_changes_returns_empty(self) -> None:
        desired_state = {
            "test_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "nullable": False,
                        "primary_key": True,
                        "autoincrement": True,
                        "default": None,
                    }
                ],
                "indexes": [],
                "unique_together": [],
            }
        }
        actual_state = {
            "test_table": {
                "columns": [
                    {
                        "name": "id",
                        "type": "integer",
                        "nullable": False,
                        "primary_key": True,
                        "default": None,
                    }
                ],
                "indexes": [],
                "unique_together": [],
            }
        }

        with (
            patch("openviper.db.schemas.sync.discover_json_schemas", return_value=desired_state),
            patch(
                "openviper.db.schemas.sync.introspect_db_schema",
                new_callable=AsyncMock,
                return_value=actual_state,
            ),
            patch("openviper.db.schemas.sync.diff_states", return_value=[]),
        ):
            sync = SchemaSync(resolved_apps={"testapp": "/tmp/testapp"})
            result = await sync.sync(verbose=False)
            assert result == []

    @pytest.mark.asyncio
    async def test_sync_with_no_schemas_returns_empty(self) -> None:
        with patch("openviper.db.schemas.sync.discover_json_schemas", return_value={}):
            sync = SchemaSync(resolved_apps={"testapp": "/tmp/testapp"})
            result = await sync.sync(verbose=False)
            assert result == []


class TestSchemaSyncFilterByApp:
    """Test that filter_by_app correctly filters tables."""

    def test_filter_returns_only_app_tables(self, tmp_path: Path) -> None:
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "ModelA.json").write_bytes(orjson.dumps(SAMPLE_SCHEMA_A))
        (schemas_dir / "ModelB.json").write_bytes(orjson.dumps(SAMPLE_SCHEMA_B))

        sync = SchemaSync(resolved_apps={"testapp": str(tmp_path)})
        filtered = sync.filter_by_app({}, "testapp")
        assert "testapp_modela" in filtered
        assert "testapp_modelb" in filtered

    def test_filter_unknown_app_returns_empty(self) -> None:
        sync = SchemaSync(resolved_apps={"testapp": "/tmp/testapp"})
        result = sync.filter_by_app({}, "unknownapp")
        assert result == {}

    def test_filter_no_resolved_apps_returns_input(self) -> None:
        sync = SchemaSync(resolved_apps=None)
        state = {"table": {"columns": [], "indexes": [], "unique_together": []}}
        result = sync.filter_by_app(state, "anyapp")
        assert result == state


class TestSchemaSyncDescribeOperation:
    """Test that describe_operation produces readable descriptions."""

    def test_describe_create_table(self) -> None:
        sync = SchemaSync()
        op = CreateTable(table_name="blog_post", columns=[])
        desc = sync.describe_operation(op)
        assert "blog_post" in desc
        assert "Create" in desc

    def test_describe_drop_table(self) -> None:
        sync = SchemaSync()
        op = DropTable(table_name="blog_post")
        desc = sync.describe_operation(op)
        assert "blog_post" in desc
        assert "Drop" in desc

    def test_describe_add_column(self) -> None:
        sync = SchemaSync()
        op = AddColumn(table_name="blog_post", column_name="title", column_type="VARCHAR(200)")
        desc = sync.describe_operation(op)
        assert "title" in desc
        assert "blog_post" in desc

    def test_describe_rename_column(self) -> None:
        sync = SchemaSync()
        op = RenameColumn(table_name="blog_post", old_name="body", new_name="content")
        desc = sync.describe_operation(op)
        assert "body" in desc
        assert "content" in desc

    def test_describe_remove_column(self) -> None:
        sync = SchemaSync()
        op = RemoveColumn(table_name="blog_post", column_name="legacy_field")
        desc = sync.describe_operation(op)
        assert "legacy_field" in desc
        assert "Remove" in desc

    def test_describe_alter_column(self) -> None:
        sync = SchemaSync()
        op = AlterColumn(table_name="blog_post", column_name="title")
        desc = sync.describe_operation(op)
        assert "title" in desc
        assert "Alter" in desc

    def test_describe_create_index(self) -> None:
        sync = SchemaSync()
        op = CreateIndex(table_name="blog_post", index_name="idx_title", columns=["title"])
        desc = sync.describe_operation(op)
        assert "idx_title" in desc
        assert "Create" in desc

    def test_describe_remove_index(self) -> None:
        sync = SchemaSync()
        op = RemoveIndex(table_name="blog_post", index_name="idx_title")
        desc = sync.describe_operation(op)
        assert "idx_title" in desc
        assert "Remove" in desc

    def test_describe_unknown_operation(self) -> None:
        sync = SchemaSync()
        desc = sync.describe_operation("not_an_operation")
        assert "not_an_operation" in desc


class TestMakemigrationsCommand:
    """Test the makemigrations command interface."""

    def test_command_has_check_argument(self) -> None:
        cmd = MakemigrationsCommand()
        parser = __import__("argparse").ArgumentParser()
        cmd.add_arguments(parser)
        actions = {a.dest for a in parser._actions}
        assert "check" in actions

    def test_command_has_force_argument(self) -> None:
        cmd = MakemigrationsCommand()
        parser = __import__("argparse").ArgumentParser()
        cmd.add_arguments(parser)
        actions = {a.dest for a in parser._actions}
        assert "force" in actions

    def test_command_help_mentions_schemas(self) -> None:
        cmd = MakemigrationsCommand()
        assert "schema" in cmd.help.lower()


class TestMigrateCommand:
    """Test the migrate command interface."""

    def test_command_has_database_argument(self) -> None:
        cmd = MigrateCommand()
        parser = __import__("argparse").ArgumentParser()
        cmd.add_arguments(parser)
        actions = {a.dest for a in parser._actions}
        assert "database" in actions

    def test_command_help_mentions_schema(self) -> None:
        cmd = MigrateCommand()
        assert "schema" in cmd.help.lower()


class TestBuiltInSchemaFiles:
    """Test that built-in app schema files exist and are valid."""

    BUILTIN_APPS = [
        ("auth", "User"),
        ("auth", "Role"),
        ("auth", "Permission"),
        ("admin", "ChangeHistory"),
        ("tasks", "TaskResult"),
        ("tasks", "ScheduledJob"),
    ]

    @pytest.mark.parametrize("app,model_name", BUILTIN_APPS)
    def test_builtin_schema_file_exists(self, app: str, model_name: str) -> None:
        base = Path(__file__).resolve().parent.parent.parent.parent
        schema_path = base / "openviper" / app / "schemas" / f"{model_name}.json"
        assert schema_path.exists(), f"Missing schema: {schema_path}"

    @pytest.mark.parametrize("app,model_name", BUILTIN_APPS)
    def test_builtin_schema_has_required_keys(self, app: str, model_name: str) -> None:
        base = Path(__file__).resolve().parent.parent.parent.parent
        schema_path = base / "openviper" / app / "schemas" / f"{model_name}.json"
        data = orjson.loads(schema_path.read_bytes())
        for key in ("model", "app", "table_name", "columns", "indexes", "unique_together"):
            assert key in data, f"Missing key '{key}' in {schema_path}"

    @pytest.mark.parametrize("app,model_name", BUILTIN_APPS)
    def test_builtin_schema_has_columns(self, app: str, model_name: str) -> None:
        base = Path(__file__).resolve().parent.parent.parent.parent
        schema_path = base / "openviper" / app / "schemas" / f"{model_name}.json"
        data = orjson.loads(schema_path.read_bytes())
        assert len(data["columns"]) > 0, f"No columns in {schema_path}"
        for col in data["columns"]:
            assert "name" in col
            assert "type" in col


class TestSqliteIndexIntrospection:
    """Test that non-unique indexes on unique columns are not filtered out.

    Regression test: a non-unique index on a column that also has a
    UNIQUE constraint was being silently dropped during introspection,
    causing repeated ``CreateIndex`` operations on every migrate run.
    """

    def test_non_unique_index_on_unique_column_is_preserved(self, tmp_path: Path) -> None:
        """A regular index on a UNIQUE column must appear in introspected indexes."""
        db_path = tmp_path / "test.db"
        engine = sa.create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(sa.text(
                'CREATE TABLE "test_table" ('
                '"id" TEXT PRIMARY KEY NOT NULL, '
                '"user_id" INTEGER NOT NULL UNIQUE REFERENCES "users"("id"), '
                '"name" TEXT)'
            ))
            conn.execute(sa.text(
                'CREATE INDEX "idx_test_table_user_id" '
                'ON "test_table" ("user_id")'
            ))

        with engine.connect() as conn:
            state = introspect_table_sync(conn, "test_table")

        index_names = {idx["name"] for idx in state["indexes"]}
        assert "idx_test_table_user_id" in index_names, (
            "Non-unique index on a UNIQUE column was incorrectly filtered out "
            "during introspection"
        )
