"""Microsoft SQL Server backup and restore engine using sqlcmd."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def _parse_mssql_url(database_url: str) -> dict[str, str]:
    """Extract MSSQL connection components from *database_url*.

    Args:
        database_url: A ``mssql://`` or ``mssql+pyodbc://`` URL.

    Returns:
        Dictionary with keys ``user``, ``password``, ``host``, ``port``,
        and ``database``.
    """
    clean_url = database_url.replace("+pyodbc", "").replace("+aioodbc", "").replace("+pymssql", "")
    parsed = urlparse(clean_url)
    return {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 1433),
        "database": parsed.path.lstrip("/"),
    }


class MSSQLBackupEngine(BackupEngine):
    """Backup and restore a SQL Server database using ``sqlcmd``."""

    engine_name = "mssql"

    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Use ``sqlcmd`` to generate a ``BACKUP DATABASE`` T-SQL script output.

        The backup is written as a ``.bak`` file (native SQL Server backup)
        referenced in ``backup.sql`` for consistency with the archive format.

        Args:
            database_url: A ``mssql://`` connection URL.
            work_dir: Directory to write ``backup.sql`` into.
            db_alias: Ignored; included for interface consistency.

        Returns:
            Path to the generated ``backup.sql`` script inside *work_dir*.

        Raises:
            RuntimeError: When ``sqlcmd`` exits with a non-zero code.
        """
        conn = _parse_mssql_url(database_url)
        dest = work_dir / "backup.sql"
        bak_path = work_dir / "backup.bak"

        backup_sql = (
            f"BACKUP DATABASE [{conn['database']}] "
            f"TO DISK = N'{bak_path}' "
            "WITH NOFORMAT, NOINIT, NAME = 'FullBackup', STATS = 10;"
        )

        returncode, _, stderr = await run_subprocess(
            [
                "sqlcmd",
                "-S",
                f"{conn['host']},{conn['port']}",
                "-U",
                conn["user"],
                "-Q",
                backup_sql,
            ],
            env={**os.environ, "SQLCMDPASSWORD": conn["password"]},
        )
        check_returncode(returncode, stderr, command="sqlcmd backup")

        dest.write_text(backup_sql, encoding="utf-8")
        return dest

    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore a SQL Server database by executing *sql_file* via ``sqlcmd``.

        Args:
            database_url: A ``mssql://`` connection URL.
            sql_file: Path to the ``.sql`` script (or ``.bak`` reference
                file) produced by :meth:`dump`.
            force: When ``True`` a ``REPLACE`` option is appended to the
                RESTORE command.

        Raises:
            RuntimeError: When ``sqlcmd`` exits with a non-zero code.
        """
        conn = _parse_mssql_url(database_url)
        bak_path = sql_file.parent / "backup.bak"
        replace_opt = "WITH REPLACE" if force else ""
        restore_sql = (
            f"RESTORE DATABASE [{conn['database']}] " f"FROM DISK = N'{bak_path}' {replace_opt};"
        )

        returncode, _, stderr = await run_subprocess(
            [
                "sqlcmd",
                "-S",
                f"{conn['host']},{conn['port']}",
                "-U",
                conn["user"],
                "-Q",
                restore_sql,
            ],
            env={**os.environ, "SQLCMDPASSWORD": conn["password"]},
        )
        check_returncode(returncode, stderr, command="sqlcmd restore")
