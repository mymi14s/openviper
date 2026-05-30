"""Unit tests for openviper.db.tools.restore.restore_engine."""

from __future__ import annotations

import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from openviper.db.tools.restore.restore_engine import (
    detect_engine_from_url,
    restore_backup,
)
from openviper.db.tools.utils.validators import ValidationError


class TestDetectEngineFromUrl:
    def test_sqlite_url(self) -> None:
        engine = detect_engine_from_url("sqlite:///db.sqlite3")
        assert engine.engine_name == "sqlite"

    def test_postgresql_url(self) -> None:
        engine = detect_engine_from_url("postgresql://u:p@host/db")
        assert engine.engine_name == "postgres"

    def test_postgres_alias(self) -> None:
        engine = detect_engine_from_url("postgres://u:p@host/db")
        assert engine.engine_name == "postgres"

    def test_postgresql_asyncpg_url(self) -> None:
        engine = detect_engine_from_url("postgresql+asyncpg://u:p@host/db")
        assert engine.engine_name == "postgres"

    def test_mysql_url(self) -> None:
        engine = detect_engine_from_url("mysql://u:p@host/db")
        assert engine.engine_name == "mariadb"

    def test_mariadb_alias(self) -> None:
        engine = detect_engine_from_url("mariadb://u:p@host/db")
        assert engine.engine_name == "mariadb"

    def test_oracle_url(self) -> None:
        engine = detect_engine_from_url("oracle://u:p@host/db")
        assert engine.engine_name == "oracle"

    def test_mssql_url(self) -> None:
        engine = detect_engine_from_url("mssql://u:p@host/db")
        assert engine.engine_name == "mssql"

    def test_unknown_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported database scheme"):
            detect_engine_from_url("redisdb://host/db")


class TestRestoreBackup:
    @pytest.mark.asyncio
    async def test_restores_from_sql_file(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "backup.sql"
        sql_file.write_bytes(b"SQL content")

        mock_engine = AsyncMock()
        mock_engine.engine_name = "sqlite"

        with patch(
            "openviper.db.tools.restore.restore_engine.detect_engine_from_url",
            return_value=mock_engine,
        ):
            await restore_backup(sql_file, "sqlite:///db.sqlite3", force=True)

        mock_engine.restore.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restores_from_tar_gz(self, tmp_path: Path) -> None:
        sql_file = tmp_path / "backup.sql"
        sql_file.write_bytes(b"SQL")
        archive = tmp_path / "backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(sql_file, arcname="backup.sql")

        mock_engine = AsyncMock()
        mock_engine.engine_name = "sqlite"

        with patch(
            "openviper.db.tools.restore.restore_engine.detect_engine_from_url",
            return_value=mock_engine,
        ):
            await restore_backup(archive, "sqlite:///db.sqlite3", force=False)

        mock_engine.restore.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_sql_in_archive_raises(self, tmp_path: Path) -> None:
        some_file = tmp_path / "other.txt"
        some_file.write_bytes(b"not sql")
        archive = tmp_path / "no_sql.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(some_file, arcname="other.txt")

        mock_engine = AsyncMock()
        mock_engine.engine_name = "sqlite"

        with patch(
            "openviper.db.tools.restore.restore_engine.detect_engine_from_url",
            return_value=mock_engine,
        ):
            with pytest.raises(ValueError, match="No 'backup.sql' member"):
                await restore_backup(archive, "sqlite:///db.sqlite3")

    @pytest.mark.asyncio
    async def test_invalid_file_raises_validation_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="not found"):
            await restore_backup(
                tmp_path / "nonexistent.tar.gz",
                "sqlite:///db.sqlite3",
            )
