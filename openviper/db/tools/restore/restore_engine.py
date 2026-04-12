"""Unified restore engine that delegates to the correct database backend."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from openviper.db.tools.backup.mariadb import MariaDBBackupEngine
from openviper.db.tools.backup.mssql import MSSQLBackupEngine
from openviper.db.tools.backup.oracle import OracleBackupEngine
from openviper.db.tools.backup.postgres import PostgresBackupEngine
from openviper.db.tools.backup.sqlite import SQLiteBackupEngine
from openviper.db.tools.compression.tar import extract_tar_gz
from openviper.db.tools.utils.validators import ValidationError, validate_backup_file

if TYPE_CHECKING:
    from openviper.db.tools.backup.base import BackupEngine

_ENGINE_REGISTRY: dict[str, type[BackupEngine]] = {
    "sqlite": SQLiteBackupEngine,
    "postgresql": PostgresBackupEngine,
    "postgres": PostgresBackupEngine,
    "mysql": MariaDBBackupEngine,
    "mariadb": MariaDBBackupEngine,
    "oracle": OracleBackupEngine,
    "mssql": MSSQLBackupEngine,
    "sqlserver": MSSQLBackupEngine,
}


def detect_engine_from_url(database_url: str) -> BackupEngine:
    """Instantiate the correct :class:`BackupEngine` for *database_url*.

    Args:
        database_url: A SQLAlchemy-style database URL.

    Returns:
        An appropriate :class:`BackupEngine` instance.

    Raises:
        ValueError: When no engine is registered for the URL scheme.
    """
    scheme = database_url.split("://")[0].split("+")[0].lower()
    engine_cls = _ENGINE_REGISTRY.get(scheme)
    if engine_cls is None:
        supported = ", ".join(sorted(_ENGINE_REGISTRY.keys()))
        raise ValueError(
            f"Unsupported database scheme '{scheme}'. " f"Supported engines: {supported}"
        )
    return engine_cls()


async def restore_backup(
    backup_file: str | Path,
    database_url: str,
    *,
    force: bool = False,
) -> None:
    """Restore a database from a ``.tar.gz`` or plain ``.sql`` backup file.

    When *backup_file* ends with ``.tar.gz`` the archive is extracted to a
    temporary directory and the ``backup.sql`` member is located.  Plain
    ``.sql`` files are used directly.

    Args:
        backup_file: Path to the backup ``.tar.gz`` or ``.sql`` file.
        database_url: SQLAlchemy-style database URL for the restore target.
        force: Pass ``True`` to allow overwriting an existing database.

    Raises:
        ValidationError: When *backup_file* fails security checks.
        ValueError: When the SQL backup file cannot be located inside the
            archive or the database URL is not supported.
        RuntimeError: When the underlying restore command fails.
    """
    safe_path = validate_backup_file(backup_file)
    engine = detect_engine_from_url(database_url)

    if safe_path.suffix == ".gz" and safe_path.stem.endswith(".tar"):
        await _restore_from_archive(safe_path, database_url, engine, force=force)
    else:
        await engine.restore(database_url, safe_path, force=force)


async def _restore_from_archive(
    archive_path: Path,
    database_url: str,
    engine: BackupEngine,
    *,
    force: bool,
) -> None:
    """Extract *archive_path* and restore from the contained ``backup.sql``."""
    with tempfile.TemporaryDirectory(prefix="openviper_restore_") as tmp:
        tmp_dir = Path(tmp)
        extracted = await extract_tar_gz(archive_path, tmp_dir)

        sql_candidates = [p for p in extracted if p.name == "backup.sql"]
        if not sql_candidates:
            raise ValueError(f"No 'backup.sql' member found in archive: {archive_path}")
        sql_file = sql_candidates[0]
        await engine.restore(database_url, sql_file, force=force)


__all__ = [
    "ValidationError",
    "detect_engine_from_url",
    "restore_backup",
]
