"""Oracle database backup and restore engine using Data Pump (expdp/impdp)."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def parse_oracle_url(database_url: str) -> dict[str, str]:
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


@contextlib.contextmanager
def oracle_par_file(conn: dict[str, str]) -> Generator[list[str]]:
    """Write a temporary Oracle Data Pump parameter file with credentials.

    Oracle Data Pump does not support reading credentials from environment
    variables.  Instead, the ``userid`` parameter in a parfile is the standard
    mechanism for passing credentials without exposing them on the command
    line (visible via ``ps`` on shared systems).

    The file is created with mode ``0o600`` and deleted on context exit.

    Yields:
        A one-element list containing ``PARFILE=<path>`` for passing to
        ``expdp``/``impdp``.
    """
    user = conn["user"]
    password = conn["password"]
    host = conn["host"]
    port = conn["port"]
    service = conn["service"]

    # Validate connection parameters to prevent injection.
    # Host, port, and service must be simple identifiers or
    # numeric values - no special characters that could alter the
    # connection string semantics.
    oracle_conn_param_re: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9._-]+$")
    if not oracle_conn_param_re.match(host):
        raise ValueError(f"Invalid Oracle host: {host!r}")
    if not port.isdigit():
        raise ValueError(f"Invalid Oracle port: {port!r}")
    if not oracle_conn_param_re.match(service):
        raise ValueError(f"Invalid Oracle service name: {service!r}")

    # Build the userid connect string with password embedded in the parfile.
    # Single quotes in the password are escaped by doubling them for the
    # Oracle parfile format.  Double quotes are also escaped to prevent
    # breaking out of the double-quote-delimited password boundary.
    if password:
        escaped_password = password.replace("'", "''").replace('"', '""')
        userid = f'{user}/"{escaped_password}"@{host}:{port}/{service}'
    else:
        userid = f"{user}@{host}:{port}/{service}"

    fd, path = tempfile.mkstemp(suffix=".par")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(f"userid={userid}\n")
        os.chmod(path, 0o600)
        yield [f"PARFILE={path}"]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


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
        conn = parse_oracle_url(database_url)
        dest_name = "backup.sql"

        # Use a parameter file for credentials to avoid exposing
        # user/password on the command line (visible via ps on shared systems).
        with oracle_par_file(conn) as par_flags:
            returncode, _, stderr = await run_subprocess(
                [
                    "expdp",
                    *cast("list[str]", par_flags),
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
        conn = parse_oracle_url(database_url)

        extra_args = ["TABLE_EXISTS_ACTION=REPLACE"] if force else ["TABLE_EXISTS_ACTION=SKIP"]

        # Use a parameter file for credentials to avoid exposing
        # user/password on the command line (visible via ps on shared systems).
        with oracle_par_file(conn) as par_flags:
            returncode, _, stderr = await run_subprocess(
                [
                    "impdp",
                    *cast("list[str]", par_flags),
                    f"DIRECTORY={sql_file.parent}",
                    f"DUMPFILE={sql_file.name}",
                    "LOGFILE=impdp_restore.log",
                    *extra_args,
                ],
            )
        check_returncode(returncode, stderr, command="impdp")
