"""Additional unit tests for openviper.db.migrations.executor.

The main migrations test suite covers many branches already; these tests target
remaining helpers and key runtime branches (verbose output, safety validation).
"""

from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

from openviper.db.migrations.executor import (
    CreateTable,
    MigrationExecutor,
    MigrationRecord,
    RunSQL,
    column_exists,
    get_dialect,
    get_existing_columns_sync,
    quote_identifier,
)


def test_get_dialect_handles_settings_attribute_error() -> None:
    get_dialect.cache_clear()

    class BrokenSettings:
        def __getattribute__(self, name: str) -> object:
            if name == "DATABASE_URL":
                raise RuntimeError("boom")
            return super().__getattribute__(name)

    with patch("openviper.db.migrations.executor.settings", BrokenSettings()):
        assert get_dialect() == "sqlite"

    get_dialect.cache_clear()


def test_quote_identifier_mssql_escapes_closing_bracket() -> None:
    assert quote_identifier("a]b", "mssql") == "[a]]b]"


def test_get_existing_columns_sync_returns_empty_set_on_inspect_error() -> None:
    mock_conn = MagicMock()
    with patch("sqlalchemy.inspect", side_effect=sa.exc.NoSuchTableError("nope")):
        assert get_existing_columns_sync(mock_conn, "missing") == set()


@pytest.mark.asyncio
async def test_column_exists_uses_run_sync_result() -> None:
    conn = MagicMock()
    conn.run_sync = AsyncMock(return_value={"id", "name"})

    assert await column_exists(conn, "t", "name") is True
    assert await column_exists(conn, "t", "missing") is False


def test_create_table_invalid_on_delete_raises_value_error() -> None:
    op = CreateTable(
        table_name="t",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "nullable": False,
            },
            {
                "name": "owner_id",
                "type": "INTEGER",
                "target_table": "owners",
                "on_delete": "DROP TABLE",
            },
        ],
    )

    with patch("openviper.db.migrations.executor.get_dialect", return_value="sqlite"):
        with pytest.raises(ValueError, match="Invalid ON DELETE action"):
            op.forward_sql()


def test_create_table_mssql_generates_fk_index_statements() -> None:
    op = CreateTable(
        table_name="things",
        columns=[
            {
                "name": "id",
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "nullable": False,
            },
            {
                "name": "owner_id",
                "type": "INTEGER",
                "nullable": False,
                "target_table": "owners",
                "on_delete": "CASCADE",
            },
        ],
    )

    with patch("openviper.db.migrations.executor.get_dialect", return_value="mssql"):
        statements = op.forward_sql()

    # Table create + 1 index for FK column
    assert any("CREATE TABLE" in str(stmt) for stmt in statements)
    assert any("CREATE INDEX" in str(stmt) for stmt in statements)
    assert any("sys.indexes" in str(stmt) for stmt in statements)


@dataclass
class DummyRow:
    app: str
    name: str


class DummyResult:
    def __init__(self) -> None:
        self._first_called = False

    def first(self):
        if self._first_called:
            return None
        self._first_called = True
        return None

    def __iter__(self):
        return iter([])


class DummyConn:
    def __init__(self) -> None:
        self.execute = AsyncMock(return_value=DummyResult())


class DummyEngine:
    def __init__(self, conn: DummyConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def begin(self):
        yield self._conn


@pytest.mark.asyncio
async def test_migrate_verbose_triggers_cache_invalidation_and_sync_warning(capsys) -> None:
    meta = sa.MetaData()
    migrations_table = sa.Table(
        "openviper_migrations",
        meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("app", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
    )

    record = MigrationRecord(
        app="myapp",
        name="0001_init",
        dependencies=[],
        operations=[RunSQL("SELECT 1")],
        path="/tmp/0001_init.py",
    )

    conn = DummyConn()
    engine = DummyEngine(conn)

    mock_invalidate_soft_removed_cache = MagicMock()

    with patch(
        "openviper.db.migrations.executor.invalidate_soft_removed_cache",
        mock_invalidate_soft_removed_cache,
    ):
        with patch("openviper.db.migrations.executor.discover_migrations", return_value=[record]):
            with patch(
                "openviper.db.migrations.executor.get_engine", new=AsyncMock(return_value=engine)
            ):
                with patch(
                    "openviper.db.migrations.executor.get_migration_table",
                    return_value=migrations_table,
                ):
                    with patch.object(
                        MigrationExecutor,
                        "_ensure_migration_table",
                        new=AsyncMock(),
                    ):
                        with patch.object(
                            MigrationExecutor,
                            "_applied_migrations",
                            new=AsyncMock(return_value=set()),
                        ):
                            with patch(
                                "openviper.db.migrations.executor.settings"
                            ) as mock_settings:
                                mock_settings.USE_TZ = False
                                mock_settings.INSTALLED_APPS = ["openviper.auth"]

                                with patch(
                                    "openviper.auth.utils.sync_content_types",
                                    new_callable=AsyncMock,
                                    side_effect=Exception("sync boom"),
                                ):
                                    with patch(
                                        "openviper.db.migrations.executor.logger"
                                    ) as mock_logger:
                                        executor = MigrationExecutor(apps_dir="apps")
                                        applied = await executor.migrate(verbose=True)

    assert applied == ["0001_init"]

    # Cache invalidation should have been attempted.
    mock_invalidate_soft_removed_cache.assert_called_once()

    # sync_content_types failure should be swallowed and logged.
    assert mock_logger.warning.called

    out = capsys.readouterr().out
    assert "Starting migrations" in out
    assert "Applying myapp - 0001_init" in out
