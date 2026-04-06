"""backup-db management command — create a compressed database backup."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from pathlib import Path

from openviper.conf import settings as _settings
from openviper.core.management.base import BaseCommand, CommandError
from openviper.db.tools.compression.tar import create_tar_gz
from openviper.db.tools.restore.restore_engine import detect_engine_from_url
from openviper.db.tools.utils.filename import (
    generate_backup_filename,
    parse_db_name_from_url,
)
from openviper.db.tools.utils.metadata import build_metadata, compute_checksum, write_metadata
from openviper.db.tools.utils.validators import validate_backup_path

_DEFAULT_BACKUP_DIR = "./backup"


class BackupDBCommand(BaseCommand):
    """Backup the configured database to a compressed ``.tar.gz`` archive."""

    help = "Backup the configured database to a tar.gz archive with UTC datetime naming."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--path",
            default=_DEFAULT_BACKUP_DIR,
            help="Directory to store the backup (default: ./backup).",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="Custom archive filename (without extension). "
            "Defaults to database_name_YYYYMMDD-HHMMSS.",
        )
        parser.add_argument(
            "--db",
            default=None,
            help="Database URL to backup. Defaults to DATABASE_URL from settings.",
        )
        parser.add_argument(
            "--compress",
            default=True,
            action=argparse.BooleanOptionalAction,
            help="Compress the backup to tar.gz (default: true).",
        )

    def handle(self, **options: object) -> None:  # type: ignore[override]
        asyncio.run(self._async_handle(**options))

    async def _async_handle(self, **options: object) -> None:
        backup_path_str = str(options.get("path") or _DEFAULT_BACKUP_DIR)
        custom_name: str | None = options.get("name")  # type: ignore[assignment]
        db_url: str | None = options.get("db")  # type: ignore[assignment]
        compress: bool = bool(options.get("compress", True))

        if not db_url:
            db_url = getattr(_settings, "DATABASE_URL", "")
        if not db_url:
            raise CommandError("No DATABASE_URL configured. Use --db to specify one.")

        backup_dir = validate_backup_path(backup_path_str)
        backup_dir.mkdir(parents=True, exist_ok=True)

        db_name = parse_db_name_from_url(db_url)
        engine = detect_engine_from_url(db_url)

        if custom_name:
            archive_name = f"{custom_name}.tar.gz" if compress else f"{custom_name}.sql"
        else:
            archive_name = generate_backup_filename(db_name, compress=compress)

        archive_path = backup_dir / archive_name

        self.stdout(self.style_notice(f"Backing up database: {db_name}"))
        self.stdout(self.style_notice(f"Engine: {engine.engine_name}"))
        self.stdout(self.style_notice(f"Output: {archive_path}"))

        with tempfile.TemporaryDirectory(prefix="openviper_backup_") as tmp:
            work_dir = Path(tmp)

            sql_file = await engine.dump(db_url, work_dir)

            if compress:
                await create_tar_gz(
                    archive_path,
                    [sql_file],
                )
                checksum = compute_checksum(archive_path)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, shutil.copy2, str(sql_file), str(archive_path))
                checksum = compute_checksum(archive_path)

            metadata = build_metadata(
                database_name=db_name,
                db_engine=engine.engine_name,
                filename=archive_name,
                checksum=checksum,
            )

            if compress:
                meta_path = work_dir / "metadata.json"
                write_metadata(metadata, meta_path)
                meta_archive = backup_dir / f"{archive_name}.meta.json"
                shutil.copy2(str(meta_path), str(meta_archive))
            else:
                write_metadata(metadata, backup_dir / f"{archive_name}.meta.json")

        self.stdout(self.style_success(f"\nBackup completed successfully: {archive_path}"))
        self.stdout(f"  Database : {db_name}")
        self.stdout(f"  Engine   : {engine.engine_name}")
        self.stdout(f"  SHA-256  : {checksum}")


Command = BackupDBCommand
