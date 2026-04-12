"""Unit tests for the restore-db CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.restore_db import RestoreDBCommand
from openviper.db.tools.utils.validators import ValidationError


class TestRestoreDBCommandAddArguments:
    def test_registers_file_argument(self) -> None:
        cmd = RestoreDBCommand()
        parser = cmd.create_parser("viperctl.py", "restore-db")
        args = parser.parse_args(["backup.tar.gz"])
        assert args.file == "backup.tar.gz"

    def test_force_defaults_to_false(self) -> None:
        cmd = RestoreDBCommand()
        parser = cmd.create_parser("viperctl.py", "restore-db")
        args = parser.parse_args(["backup.tar.gz"])
        assert args.force is False

    def test_force_flag_sets_true(self) -> None:
        cmd = RestoreDBCommand()
        parser = cmd.create_parser("viperctl.py", "restore-db")
        args = parser.parse_args(["backup.tar.gz", "--force"])
        assert args.force is True

    def test_db_flag_accepted(self) -> None:
        cmd = RestoreDBCommand()
        parser = cmd.create_parser("viperctl.py", "restore-db")
        args = parser.parse_args(["backup.tar.gz", "--db", "postgresql://u:p@h/db"])
        assert args.db == "postgresql://u:p@h/db"


class TestRestoreDBCommandAsyncHandle:
    @pytest.mark.asyncio
    async def test_successful_restore_calls_restore_backup(self, tmp_path: Path) -> None:
        backup_file = tmp_path / "backup.tar.gz"
        backup_file.write_bytes(b"fake archive")

        cmd = RestoreDBCommand()
        with patch(
            "openviper.core.management.commands.restore_db.restore_backup",
            new_callable=AsyncMock,
        ) as mock_restore:
            await cmd._async_handle(
                file=str(backup_file),
                force=True,
                db="sqlite:///db.sqlite3",
            )

        mock_restore.assert_awaited_once_with(
            str(backup_file),
            "sqlite:///db.sqlite3",
            force=True,
        )

    @pytest.mark.asyncio
    async def test_validation_error_wrapped_as_command_error(self) -> None:
        cmd = RestoreDBCommand()
        with patch(
            "openviper.core.management.commands.restore_db.restore_backup",
            new_callable=AsyncMock,
            side_effect=ValidationError("path traversal"),
        ):
            with pytest.raises(CommandError, match="path traversal"):
                await cmd._async_handle(
                    file="bad_path",
                    force=False,
                    db="sqlite:///db.sqlite3",
                )

    @pytest.mark.asyncio
    async def test_no_db_url_raises_command_error(self) -> None:
        cmd = RestoreDBCommand()
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = ""

        with patch("openviper.core.management.commands.restore_db._settings", mock_settings):
            with pytest.raises(CommandError, match="No DATABASE_URL"):
                await cmd._async_handle(
                    file="backup.tar.gz",
                    force=False,
                    db=None,
                )

    @pytest.mark.asyncio
    async def test_uses_settings_db_url_when_not_given(self, tmp_path: Path) -> None:
        backup_file = tmp_path / "backup.tar.gz"
        backup_file.write_bytes(b"data")
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "sqlite:///settings.db"

        cmd = RestoreDBCommand()
        with patch("openviper.core.management.commands.restore_db._settings", mock_settings):
            with patch(
                "openviper.core.management.commands.restore_db.restore_backup",
                new_callable=AsyncMock,
            ) as mock_restore:
                await cmd._async_handle(
                    file=str(backup_file),
                    force=False,
                    db=None,
                )

        mock_restore.assert_awaited_once_with(
            str(backup_file),
            "sqlite:///settings.db",
            force=False,
        )

    @pytest.mark.asyncio
    async def test_file_not_found_wrapped_as_command_error(self) -> None:
        cmd = RestoreDBCommand()
        with patch(
            "openviper.core.management.commands.restore_db.restore_backup",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("backup not found"),
        ):
            with pytest.raises(CommandError, match="backup not found"):
                await cmd._async_handle(
                    file="missing.tar.gz",
                    force=False,
                    db="sqlite:///db.sqlite3",
                )
