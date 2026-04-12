"""Integration tests for the complete SQLite backup and restore workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openviper.core.management.commands.backup_db import BackupDBCommand
from openviper.core.management.commands.restore_db import RestoreDBCommand
from openviper.db.tools.compression.tar import list_tar_gz_members


class TestSQLiteFullBackupWorkflow:
    @pytest.mark.asyncio
    async def test_full_backup_produces_valid_archive(self, tmp_path: Path) -> None:
        db_file = tmp_path / "app.sqlite3"
        db_file.write_bytes(b"SQLite file content")
        backup_dir = tmp_path / "backups"

        cmd = BackupDBCommand()
        await cmd._async_handle(
            path=str(backup_dir),
            name=None,
            db=f"sqlite:///{db_file}",
            compress=True,
        )

        archives = list(backup_dir.glob("*.tar.gz"))
        assert len(archives) == 1

        members = list_tar_gz_members(archives[0])
        assert "backup.sql" in members

    @pytest.mark.asyncio
    async def test_backup_creates_metadata_sidecar(self, tmp_path: Path) -> None:
        db_file = tmp_path / "meta.sqlite3"
        db_file.write_bytes(b"data")
        backup_dir = tmp_path / "backups"

        cmd = BackupDBCommand()
        await cmd._async_handle(
            path=str(backup_dir),
            name="testbackup",
            db=f"sqlite:///{db_file}",
            compress=True,
        )

        sidecar = backup_dir / "testbackup.tar.gz.meta.json"
        assert sidecar.exists()
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        assert meta["db_engine"] == "sqlite"
        assert "checksum" in meta
        assert "timestamp" in meta

    @pytest.mark.asyncio
    async def test_uncompressed_backup_produces_sql_file(self, tmp_path: Path) -> None:
        db_file = tmp_path / "raw.sqlite3"
        db_file.write_bytes(b"SQLite raw")
        backup_dir = tmp_path / "backups"

        cmd = BackupDBCommand()
        await cmd._async_handle(
            path=str(backup_dir),
            name="rawbackup",
            db=f"sqlite:///{db_file}",
            compress=False,
        )

        assert (backup_dir / "rawbackup.sql").exists()


class TestSQLiteFullRestoreWorkflow:
    @pytest.mark.asyncio
    async def test_restore_from_archive_recreates_db(self, tmp_path: Path) -> None:
        db_file = tmp_path / "original.sqlite3"
        db_file.write_bytes(b"original SQLite data")

        backup_dir = tmp_path / "backups"
        cmd = BackupDBCommand()
        await cmd._async_handle(
            path=str(backup_dir),
            name="backup",
            db=f"sqlite:///{db_file}",
            compress=True,
        )

        archive = backup_dir / "backup.tar.gz"
        restore_db = tmp_path / "restored.sqlite3"

        restore_cmd = RestoreDBCommand()
        await restore_cmd._async_handle(
            file=str(archive),
            force=True,
            db=f"sqlite:///{restore_db}",
        )

        assert restore_db.exists()
        assert restore_db.read_bytes() == b"original SQLite data"

    @pytest.mark.asyncio
    async def test_restore_without_force_raises_when_target_exists(self, tmp_path: Path) -> None:
        from openviper.core.management.base import CommandError

        db_file = tmp_path / "src.sqlite3"
        db_file.write_bytes(b"data")
        backup_dir = tmp_path / "backups"

        cmd = BackupDBCommand()
        await cmd._async_handle(
            path=str(backup_dir),
            name="bkp",
            db=f"sqlite:///{db_file}",
            compress=True,
        )
        archive = backup_dir / "bkp.tar.gz"

        target_db = tmp_path / "existing.sqlite3"
        target_db.write_bytes(b"existing")

        restore_cmd = RestoreDBCommand()
        with pytest.raises(CommandError):
            await restore_cmd._async_handle(
                file=str(archive),
                force=False,
                db=f"sqlite:///{target_db}",
            )
