"""Abstract base class for database backup engines."""

from __future__ import annotations

import abc
from pathlib import Path


class BackupEngine(abc.ABC):
    """Abstract base class that all database backup engines must implement.

    Each concrete engine is responsible for dumping its database to a
    single ``.sql`` (or equivalent) file inside *work_dir* and returning
    the path to that file.
    """

    #: Human-readable identifier for this engine, e.g. ``"sqlite"``.
    engine_name: str = ""

    @abc.abstractmethod
    async def dump(
        self,
        database_url: str,
        work_dir: Path,
        *,
        db_alias: str = "default",
    ) -> Path:
        """Dump the database to a file inside *work_dir*.

        Args:
            database_url: SQLAlchemy-style database URL.
            work_dir: Temporary working directory to write intermediate files.
            db_alias: Logical alias used for naming the dump file.

        Returns:
            Path to the generated ``.sql`` file within *work_dir*.
        """
        ...

    @abc.abstractmethod
    async def restore(
        self,
        database_url: str,
        sql_file: Path,
        *,
        force: bool = False,
    ) -> None:
        """Restore the database from *sql_file*.

        Args:
            database_url: SQLAlchemy-style database URL.
            sql_file: Path to the ``.sql`` dump file to restore.
            force: When ``True`` the caller has already confirmed that
                existing data may be overwritten.
        """
        ...
