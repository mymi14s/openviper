"""Oracle database backup and restore engine using Data Pump (expdp/impdp)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def _parse_oracle_url(database_url: str) -> dict[str, str]:
    """Extract Oracle connection components from *database_url*.

    Args:
        database_url: An ``oracle://`` or ``oracle+oracledb://`` URL.

    Returns:
        Dictionary with keys ``user``, ``password``, ``host``, ``port``,
        and ``service`` (the database service name).
    """
    clean_url = database_url.replace("+oracledb", "")
    parsed = urlparse(clean_url)
    return {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 1521),
        "service": parsed.path.lstrip("/"),
    }


class OracleBackupEngine(BackupEngine):
    """Backup and restore an Oracle database using ``expdp`` / ``impdp``."""

    engine_name = "oracle"

    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Run ``expdp`` to create a Data Pump export in *work_dir*.

        The export file is written to *work_dir* as ``backup.sql`` (the file
        is actually a Data Pump ``.dmp`` file but uses the common name for
        uniformity with other engines).

        Args:
            database_url: An ``oracle://`` connection URL.
            work_dir: Working directory; ``expdp`` uses ``DIRECTORY`` pointing
                here.
            db_alias: Ignored; included for interface consistency.

        Returns:
            Path to the generated dump file inside *work_dir*.

        Raises:
            RuntimeError: When ``expdp`` exits with a non-zero code.
        """
        conn = _parse_oracle_url(database_url)
        user = conn["user"]
        password = conn["password"]
        host = conn["host"]
        port = conn["port"]
        service = conn["service"]
        credentials = f"{user}/{password}@{host}:{port}/{service}"
        dest_name = "backup.sql"

        returncode, _, stderr = await run_subprocess(
            [
                "expdp",
                credentials,
                f"DIRECTORY={work_dir}",
                f"DUMPFILE={dest_name}",
                "LOGFILE=expdp_backup.log",
            ],
        )
        check_returncode(returncode, stderr, command="expdp")
        return work_dir / dest_name

    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore an Oracle database from a Data Pump dump file via ``impdp``.

        Args:
            database_url: An ``oracle://`` connection URL.
            sql_file: Path to the ``.sql`` / ``.dmp`` dump file.
            force: When ``True`` passes ``TABLE_EXISTS_ACTION=REPLACE`` to
                ``impdp`` so existing objects are replaced.

        Raises:
            RuntimeError: When ``impdp`` exits with a non-zero code.
        """
        conn = _parse_oracle_url(database_url)
        user = conn["user"]
        password = conn["password"]
        host = conn["host"]
        port = conn["port"]
        service = conn["service"]
        credentials = f"{user}/{password}@{host}:{port}/{service}"

        extra_args = ["TABLE_EXISTS_ACTION=REPLACE"] if force else ["TABLE_EXISTS_ACTION=SKIP"]

        returncode, _, stderr = await run_subprocess(
            [
                "impdp",
                credentials,
                f"DIRECTORY={sql_file.parent}",
                f"DUMPFILE={sql_file.name}",
                "LOGFILE=impdp_restore.log",
                *extra_args,
            ],
        )
        check_returncode(returncode, stderr, command="impdp")
