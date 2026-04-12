"""Unit tests for the backup-db CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.backup_db import BackupDBCommand


class TestBackupDBCommandAddArguments:
    def test_registers_all_arguments(self) -> None:
        cmd = BackupDBCommand()
        parser = cmd.create_parser("viperctl.py", "backup-db")
        # Should not raise
        args = parser.parse_args(
            ["--path", "/tmp/backups", "--name", "mybackup", "--db", "sqlite:///x.db"]
        )
        assert args.path == "/tmp/backups"
        assert args.name == "mybackup"
        assert args.db == "sqlite:///x.db"

    def test_compress_defaults_to_true(self) -> None:
        cmd = BackupDBCommand()
        parser = cmd.create_parser("viperctl.py", "backup-db")
        args = parser.parse_args([])
        assert args.compress is True

    def test_no_compress_flag(self) -> None:
        cmd = BackupDBCommand()
        parser = cmd.create_parser("viperctl.py", "backup-db")
        args = parser.parse_args(["--no-compress"])
        assert args.compress is False


class TestBackupDBCommandAsyncHandle:
    @pytest.mark.asyncio
    async def test_creates_tar_gz_archive(self, tmp_path: Path) -> None:
        db_file = tmp_path / "db.sqlite3"
        db_file.write_bytes(b"SQLite")
        backup_dir = tmp_path / "backup"

        cmd = BackupDBCommand()
        mock_engine = MagicMock()
        mock_engine.engine_name = "sqlite"

        async def fake_dump(url, work_dir, db_alias="default"):
            dest = work_dir / "backup.sql"
            dest.write_bytes(b"SQLite data")
            return dest

        mock_engine.dump = fake_dump

        with patch(
            "openviper.core.management.commands.backup_db.detect_engine_from_url",
            return_value=mock_engine,
        ):
            await cmd._async_handle(
                path=str(backup_dir),
                name=None,
                db="sqlite:///db.sqlite3",
                compress=True,
            )

        archives = list(backup_dir.glob("*.tar.gz"))
        assert len(archives) == 1

    @pytest.mark.asyncio
    async def test_uses_settings_database_url_when_db_not_given(self, tmp_path: Path) -> None:
        backup_dir = tmp_path / "backup"
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "sqlite:///settings_db.sqlite3"

        mock_engine = MagicMock()
        mock_engine.engine_name = "sqlite"

        async def fake_dump(url, work_dir, db_alias="default"):
            dest = work_dir / "backup.sql"
            dest.write_bytes(b"data")
            return dest

        mock_engine.dump = fake_dump

        cmd = BackupDBCommand()
        with patch("openviper.core.management.commands.backup_db._settings", mock_settings):
            with patch(
                "openviper.core.management.commands.backup_db.detect_engine_from_url",
                return_value=mock_engine,
            ):
                await cmd._async_handle(
                    path=str(backup_dir),
                    name=None,
                    db=None,
                    compress=True,
                )

        archives = list(backup_dir.glob("*.tar.gz"))
        assert len(archives) == 1

    @pytest.mark.asyncio
    async def test_no_db_url_raises_command_error(self, tmp_path: Path) -> None:
        from openviper.core.management.base import CommandError

        cmd = BackupDBCommand()
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = ""

        with patch("openviper.core.management.commands.backup_db._settings", mock_settings):
            with pytest.raises(CommandError, match="No DATABASE_URL"):
                await cmd._async_handle(
                    path=str(tmp_path),
                    name=None,
                    db=None,
                    compress=True,
                )

    @pytest.mark.asyncio
    async def test_custom_name_used_in_filename(self, tmp_path: Path) -> None:
        backup_dir = tmp_path / "backup"
        mock_engine = MagicMock()
        mock_engine.engine_name = "sqlite"

        async def fake_dump(url, work_dir, db_alias="default"):
            dest = work_dir / "backup.sql"
            dest.write_bytes(b"data")
            return dest

        mock_engine.dump = fake_dump

        cmd = BackupDBCommand()
        with patch(
            "openviper.core.management.commands.backup_db.detect_engine_from_url",
            return_value=mock_engine,
        ):
            await cmd._async_handle(
                path=str(backup_dir),
                name="my_custom_backup",
                db="sqlite:///db.sqlite3",
                compress=True,
            )

        assert (backup_dir / "my_custom_backup.tar.gz").exists()
