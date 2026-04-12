"""MariaDB / MySQL backup and restore engine using mysqldump / mysql."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

from openviper.db.tools.backup.base import BackupEngine
from openviper.db.tools.utils.async_process import check_returncode, run_subprocess


def _build_mysql_args(database_url: str) -> tuple[list[str], str, str]:
    """Parse *database_url* into mysqldump connection arguments.

    The password is returned separately so callers can supply it via a
    temporary options file rather than as a command-line argument, preventing
    it from appearing in process listings.

    Args:
        database_url: A ``mysql://`` or ``mysql+aiomysql://`` URL.

    Returns:
        A 3-tuple of ``(connection_flags, db_name, password)``.
    """
    clean_url = database_url.replace("+aiomysql", "").replace("+pymysql", "")
    parsed = urlparse(clean_url)

    flags: list[str] = []
    if parsed.hostname:
        flags += [f"--host={parsed.hostname}"]
    if parsed.port:
        flags += [f"--port={parsed.port}"]
    if parsed.username:
        flags += [f"--user={parsed.username}"]

    db_name = parsed.path.lstrip("/")
    password = parsed.password or ""
    return flags, db_name, password


@contextlib.contextmanager
def _mysql_defaults_file(password: str) -> Generator[list[str]]:
    """Write a temporary MySQL options file and yield a ``--defaults-file`` flag.

    The file is created with mode ``0o600`` so only the current user can
    read it.  It is unconditionally deleted when the context exits.

    ``--defaults-file`` must be the *first* argument to ``mysqldump``/``mysql``
    when used; callers should prepend the yielded list to their argument list.

    Args:
        password: The plain-text password to embed in the options file.

    Yields:
        A one-element list containing ``--defaults-file=<path>`` when
        *password* is non-empty, or an empty list when there is no password.
    """
    if not password:
        yield []
        return

    fd, path = tempfile.mkstemp(suffix=".cnf")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(f"[client]\npassword={password}\n")
        os.chmod(path, 0o600)
        yield [f"--defaults-file={path}"]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


class MariaDBBackupEngine(BackupEngine):
    """Backup and restore a MariaDB/MySQL database using ``mysqldump``."""

    engine_name = "mariadb"

    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Run ``mysqldump`` to create a plain-SQL dump in *work_dir*.

        Args:
            database_url: A ``mysql://`` connection URL.
            work_dir: Directory to write ``backup.sql`` into.
            db_alias: Ignored; included for interface consistency.

        Returns:
            Path to the generated ``backup.sql``.

        Raises:
            RuntimeError: When ``mysqldump`` exits with a non-zero code.
        """
        dest = work_dir / "backup.sql"
        flags, db_name, password = _build_mysql_args(database_url)

        with _mysql_defaults_file(password) as defaults_flags:
            returncode, stdout, stderr = await run_subprocess(
                ["mysqldump", *defaults_flags, "--single-transaction", *flags, db_name],
            )
        check_returncode(returncode, stderr, command="mysqldump")
        dest.write_text(stdout, encoding="utf-8")
        return dest

    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore a MariaDB/MySQL database from a plain-SQL dump via ``mysql``.

        Args:
            database_url: A ``mysql://`` connection URL.
            sql_file: Path to the ``.sql`` dump file.
            force: Unused; the caller controls database state before restore.

        Raises:
            RuntimeError: When ``mysql`` exits with a non-zero code.
        """
        flags, db_name, password = _build_mysql_args(database_url)

        with _mysql_defaults_file(password) as defaults_flags:
            returncode, _, stderr = await run_subprocess(
                ["mysql", *defaults_flags, *flags, db_name, "--execute", f"source {sql_file}"],
            )
        check_returncode(returncode, stderr, command="mysql")
