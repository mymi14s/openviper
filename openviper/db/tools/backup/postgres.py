"""PostgreSQL backup and restore engine using pg_dump / psql."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def _build_pg_env(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Parse *database_url* into pg_dump argument fragments and env vars.

    Credentials are passed via the ``PGPASSWORD`` environment variable so
    they never appear on the process command line (which is visible to
    other processes via ``ps``).

    Args:
        database_url: A ``postgresql://`` or ``postgresql+asyncpg://`` URL.

    Returns:
        A 2-tuple of ``(connection_flags, env_dict)`` where
        *connection_flags* is a list of ``-h``/``-p``/``-U``/``-d`` flags
        and *env_dict* contains ``PGPASSWORD`` when a password is present.
    """
    clean_url = database_url.replace("+asyncpg", "").replace("+psycopg2", "")
    parsed = urlparse(clean_url)

    flags: list[str] = []
    env: dict[str, str] = dict(os.environ)

    if parsed.hostname:
        flags += ["-h", parsed.hostname]
    if parsed.port:
        flags += ["-p", str(parsed.port)]
    if parsed.username:
        flags += ["-U", parsed.username]
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    db_name = parsed.path.lstrip("/")
    if db_name:
        flags += ["-d", db_name]

    return flags, env


class PostgresBackupEngine(BackupEngine):
    """Backup and restore a PostgreSQL database using ``pg_dump`` / ``psql``."""

    engine_name = "postgres"

    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Run ``pg_dump`` to create a plain-SQL dump in *work_dir*.

        Args:
            database_url: A ``postgresql://`` connection URL.
            work_dir: Directory to write ``backup.sql`` into.
            db_alias: Ignored; included for interface consistency.

        Returns:
            Path to the generated ``backup.sql``.

        Raises:
            RuntimeError: When ``pg_dump`` exits with a non-zero code.
        """
        dest = work_dir / "backup.sql"
        flags, env = _build_pg_env(database_url)

        returncode, _, stderr = await run_subprocess(
            ["pg_dump", "--no-password", "--format=plain", *flags, "-f", str(dest)],
            env=env,
        )
        check_returncode(returncode, stderr, command="pg_dump")
        return dest

    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore a PostgreSQL database from a plain-SQL dump via ``psql``.

        Args:
            database_url: A ``postgresql://`` connection URL.
            sql_file: Path to the ``.sql`` dump file.
            force: Unused for Postgres; ``psql`` does not require a flag to
                overwrite — the caller is responsible for database state.

        Raises:
            RuntimeError: When ``psql`` exits with a non-zero code.
        """
        flags, env = _build_pg_env(database_url)

        returncode, _, stderr = await run_subprocess(
            ["psql", "--no-password", *flags, "-f", str(sql_file)],
            env=env,
        )
        check_returncode(returncode, stderr, command="psql")
