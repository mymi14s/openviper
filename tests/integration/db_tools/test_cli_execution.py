"""Integration tests for the management command entry-points discovery."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management import find_command
from openviper.core.management.base import CommandError
from openviper.core.management.commands.backup_db import BackupDBCommand
from openviper.core.management.commands.restore_db import RestoreDBCommand


class TestEntryPointsDiscovery:
    def testfind_command_discovers_backup_db_via_entry_points(self) -> None:
        find_command.cache_clear()

        mock_ep = MagicMock()
        mock_ep.name = "backup-db"

        mock_ep.load.return_value = BackupDBCommand

        with patch(
            "openviper.core.management.importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            cmd = find_command("backup-db")

        assert isinstance(cmd, BackupDBCommand)
        find_command.cache_clear()

    def testfind_command_discovers_restore_db_via_entry_points(self) -> None:
        find_command.cache_clear()

        mock_ep = MagicMock()
        mock_ep.name = "restore-db"

        mock_ep.load.return_value = RestoreDBCommand

        with patch(
            "openviper.core.management.importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            cmd = find_command("restore-db")

        assert isinstance(cmd, RestoreDBCommand)
        find_command.cache_clear()

    def test_entry_points_exception_falls_through_to_unknown_command(self) -> None:
        find_command.cache_clear()

        with patch(
            "openviper.core.management.importlib.metadata.entry_points",
            side_effect=Exception("ep discovery error"),
        ):
            with pytest.raises(CommandError, match="Unknown command"):
                find_command("nonexistent-plugin-cmd")

        find_command.cache_clear()


class TestMetadataValidation:
    def test_backup_archive_metadata_fields_are_complete(self, tmp_path) -> None:
        async def run() -> None:
            db_file = tmp_path / "validate.sqlite3"
            db_file.write_bytes(b"data")
            backup_dir = tmp_path / "backup"

            cmd = BackupDBCommand()
            await cmd.async_handle(
                path=str(backup_dir),
                name="validated",
                db=f"sqlite:///{db_file}",
                compress=True,
            )

        asyncio.run(run())

        sidecar = tmp_path / "backup" / "validated.tar.gz.meta.json"
        meta = json.loads(sidecar.read_text(encoding="utf-8"))

        required_fields = {
            "database_name",
            "db_engine",
            "timestamp",
            "filename",
            "openviper_version",
            "checksum",
        }
        assert required_fields.issubset(meta.keys())
