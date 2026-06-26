"""Microsoft SQL Server backup and restore engine using sqlcmd."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def parse_mssql_url(database_url: str) -> dict[str, str]:
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


def escape_mssql_identifier(identifier: str) -> str:
    """Escape a SQL Server bracket-delimited identifier."""
    return identifier.replace("]", "]]")


@contextlib.contextmanager
def sqlcmd_input_file(sql: str) -> Generator[Path]:
    """Write *sql* to a private temporary file for ``sqlcmd -i``."""
    fd, path = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(sql)
        os.chmod(path, 0o600)
        yield Path(path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


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
        conn = parse_mssql_url(database_url)
        dest = work_dir / "backup.sql"
        bak_path = work_dir / "backup.bak"

        # Escape single quotes in the path to prevent T-SQL injection.
        safe_bak_path = str(bak_path).replace("'", "''")
        safe_database = escape_mssql_identifier(conn["database"])

        backup_sql = (
            f"BACKUP DATABASE [{safe_database}] "
            f"TO DISK = N'{safe_bak_path}' "
            "WITH NOFORMAT, NOINIT, NAME = 'FullBackup', STATS = 10;"
        )

        with sqlcmd_input_file(backup_sql) as query_file:
            returncode, _, stderr = await run_subprocess(
                [
                    "sqlcmd",
                    "-S",
                    f"{conn['host']},{conn['port']}",
                    "-U",
                    conn["user"],
                    "-i",
                    str(query_file),
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
        conn = parse_mssql_url(database_url)
        bak_path = sql_file.parent / "backup.bak"
        # Escape single quotes in the path and database name to prevent
        # T-SQL injection via crafted paths or database names.
        safe_bak_path = str(bak_path).replace("'", "''")
        safe_database = escape_mssql_identifier(conn["database"])
        replace_opt = "WITH REPLACE" if force else ""
        restore_sql = (
            f"RESTORE DATABASE [{safe_database}] FROM DISK = N'{safe_bak_path}' {replace_opt};"
        )

        with sqlcmd_input_file(restore_sql) as query_file:
            returncode, _, stderr = await run_subprocess(
                [
                    "sqlcmd",
                    "-S",
                    f"{conn['host']},{conn['port']}",
                    "-U",
                    conn["user"],
                    "-i",
                    str(query_file),
                ],
                env={**os.environ, "SQLCMDPASSWORD": conn["password"]},
            )
        check_returncode(returncode, stderr, command="sqlcmd restore")
