"""restore-db management command — restore a database from a backup archive."""

from __future__ import annotations

import argparse
import asyncio

from openviper.conf import settings as _settings
from openviper.core.management.base import BaseCommand, CommandError
from openviper.db.tools.restore.restore_engine import restore_backup
from openviper.db.tools.utils.validators import ValidationError


class RestoreDBCommand(BaseCommand):
    """Restore the configured database from a ``.tar.gz`` or ``.sql`` backup."""

    help = "Restore a database from a tar.gz or sql backup file."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "file",
            help="Path to the backup file (.tar.gz or .sql).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Overwrite the existing database without prompting.",
        )
        parser.add_argument(
            "--db",
            default=None,
            help="Database URL to restore into. Defaults to DATABASE_URL from settings.",
        )

    def handle(self, **options: object) -> None:  # type: ignore[override]
        asyncio.run(self._async_handle(**options))

    async def _async_handle(self, **options: object) -> None:
        backup_file: str = str(options["file"])
        force: bool = bool(options.get("force", False))
        db_url: str | None = options.get("db")  # type: ignore[assignment]

        if not db_url:
            db_url = getattr(_settings, "DATABASE_URL", "")
        if not db_url:
            raise CommandError("No DATABASE_URL configured. Use --db to specify one.")

        self.stdout(self.style_notice(f"Restoring database from: {backup_file}"))

        if not force:
            self.stdout(
                self.style_warning(
                    "Warning: This will overwrite the existing database. " "Use --force to confirm."
                )
            )

        try:
            await restore_backup(backup_file, db_url, force=force)
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        except FileExistsError as exc:
            raise CommandError(str(exc)) from exc
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout(self.style_success("\nDatabase restored successfully."))
        self.stdout(f"  Source: {backup_file}")


Command = RestoreDBCommand
