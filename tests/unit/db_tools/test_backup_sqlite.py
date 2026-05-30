"""Unit tests for the SQLite backup engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openviper.db.tools.backup.sqlite import SQLiteBackupEngine


class TestSQLiteBackupEngineExtractPath:
    def test_sqlite_triple_slash_url(self) -> None:
        engine = SQLiteBackupEngine()
        path = engine._extract_db_path("sqlite:///mydb.sqlite3")
        assert str(path) == "mydb.sqlite3"

    def test_sqlite_asyncio_url(self) -> None:
        engine = SQLiteBackupEngine()
        path = engine._extract_db_path("sqlite+aiosqlite:///db.sqlite3")
        assert str(path) == "db.sqlite3"

    def test_in_memory_url_raises(self) -> None:
        engine = SQLiteBackupEngine()
        with pytest.raises(ValueError, match="In-memory"):
            engine._extract_db_path("sqlite:///:memory:")


class TestSQLiteBackupEngineDump:
    @pytest.mark.asyncio
    async def test_copies_db_file_to_work_dir(self, tmp_path: Path) -> None:
        db_file = tmp_path / "mydb.sqlite3"
        db_file.write_bytes(b"SQLite binary data")

        work_dir = tmp_path / "work"
        work_dir.mkdir()

        engine = SQLiteBackupEngine()
        with patch.object(engine, "_extract_db_path", return_value=db_file):
            result = await engine.dump("sqlite:///mydb.sqlite3", work_dir)

        assert result == work_dir / "backup.sql"
        assert (work_dir / "backup.sql").read_bytes() == b"SQLite binary data"

    def test_engine_name_is_sqlite(self) -> None:
        assert SQLiteBackupEngine.engine_name == "sqlite"


class TestSQLiteBackupEngineRestore:
    @pytest.mark.asyncio
    async def test_restores_file_to_db_path(self, tmp_path: Path) -> None:
        backup = tmp_path / "backup.sql"
        backup.write_bytes(b"SQLite data")
        db_file = tmp_path / "restored.sqlite3"

        engine = SQLiteBackupEngine()
        with patch.object(engine, "_extract_db_path", return_value=db_file):
            await engine.restore("sqlite:///restored.sqlite3", backup, force=True)

        assert db_file.read_bytes() == b"SQLite data"

    @pytest.mark.asyncio
    async def test_existing_db_without_force_raises(self, tmp_path: Path) -> None:
        backup = tmp_path / "backup.sql"
        backup.write_bytes(b"data")
        db_file = tmp_path / "existing.sqlite3"
        db_file.write_bytes(b"existing")

        engine = SQLiteBackupEngine()
        with patch.object(engine, "_extract_db_path", return_value=db_file):
            with pytest.raises(FileExistsError, match="already exists"):
                await engine.restore("sqlite:///existing.sqlite3", backup, force=False)

    @pytest.mark.asyncio
    async def test_force_true_overwrites_existing(self, tmp_path: Path) -> None:
        backup = tmp_path / "backup.sql"
        backup.write_bytes(b"new data")
        db_file = tmp_path / "target.sqlite3"
        db_file.write_bytes(b"old data")

        engine = SQLiteBackupEngine()
        with patch.object(engine, "_extract_db_path", return_value=db_file):
            await engine.restore("sqlite:///target.sqlite3", backup, force=True)

        assert db_file.read_bytes() == b"new data"
