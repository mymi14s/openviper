"""SQLite backup and restore engine."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from openviper.db.tools.backup.base import BackupEngine


class SQLiteBackupEngine(BackupEngine):
    """Backup and restore a SQLite database by copying the database file."""

    engine_name = "sqlite"

    def _extract_db_path(self, database_url: str) -> Path:
        """Return the filesystem path encoded in a ``sqlite:///`` URL.

        Args:
            database_url: A URL like ``"sqlite:///path/to/db.sqlite3"`` or
                ``"sqlite+aiosqlite:///path/to/db.sqlite3"``.

        Returns:
            Resolved :class:`~pathlib.Path` to the SQLite database file.

        Raises:
            ValueError: When the URL does not point to a file-backed database.
        """
        parts = database_url.split("///", 1)
        if len(parts) != 2 or not parts[1]:
            raise ValueError("In-memory SQLite databases cannot be backed up.")
        db_path_str = parts[1]
        if db_path_str in (":memory:", "/:memory:"):
            raise ValueError("In-memory SQLite databases cannot be backed up.")
        return Path(db_path_str)

    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Copy the SQLite database file to *work_dir* as ``backup.sql``.

        Although this copies the raw database file rather than generating
        real SQL, the destination is named ``backup.sql`` for consistency
        with the archive format.  The ``metadata.json`` identifies the
        engine so restore logic handles it correctly.

        Args:
            database_url: A ``sqlite:///`` URL.
            work_dir: Directory to place the copied database file.
            db_alias: Ignored; included for interface consistency.

        Returns:
            Path to the copied file inside *work_dir*.
        """
        db_path = self._extract_db_path(database_url)
        dest = work_dir / "backup.sql"

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, shutil.copy2, str(db_path), str(dest))
        return dest

    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore the SQLite database by copying *sql_file* back.

        Args:
            database_url: A ``sqlite:///`` URL.
            sql_file: Path to the backup file (raw SQLite file).
            force: When ``False`` and the target already exists, a
                :exc:`FileExistsError` is raised instead of overwriting.

        Raises:
            FileExistsError: When the target exists and *force* is ``False``.
        """
        db_path = self._extract_db_path(database_url)

        if db_path.exists() and not force:
            raise FileExistsError(
                f"Database file already exists: {db_path}. " "Use --force to overwrite."
            )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, shutil.copy2, str(sql_file), str(db_path))
