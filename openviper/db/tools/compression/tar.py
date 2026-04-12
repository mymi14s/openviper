"""Safe tar.gz archive creation and extraction for database backups."""

from __future__ import annotations

import asyncio
import tarfile
from pathlib import Path

from openviper.db.tools.utils.validators import validate_archive_member


async def create_tar_gz(archive_path: Path, source_files: list[Path]) -> None:
    """Create a ``tar.gz`` archive from *source_files*.

    Files are written with their bare filenames only (no directory structure)
    to avoid accidentally embedding absolute paths inside the archive.

    This operation is dispatched to a thread-pool executor so it does not
    block the event loop.

    Args:
        archive_path: Destination ``.tar.gz`` file path.
        archive_path.parent must exist before calling this function.
        source_files: List of files to include in the archive.

    Raises:
        FileNotFoundError: When any source file does not exist.
    """
    for src in source_files:
        if not src.exists():
            raise FileNotFoundError(f"Source file not found for archiving: {src}")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        _create_tar_gz_sync,
        archive_path,
        source_files,
    )


def _create_tar_gz_sync(archive_path: Path, source_files: list[Path]) -> None:
    """Synchronous inner implementation of :func:`create_tar_gz`."""
    with tarfile.open(archive_path, "w:gz") as tar:
        for src in source_files:
            tar.add(src, arcname=src.name)


async def extract_tar_gz(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Extract a ``tar.gz`` archive into *dest_dir* with path-traversal protection.

    Each member path is validated so that no file is extracted outside
    *dest_dir* (prevents "tar-slip" / "zip-slip" attacks).

    This operation is dispatched to a thread-pool executor.

    Args:
        archive_path: Path to the ``.tar.gz`` file.
        dest_dir: Directory to extract into (created if absent).

    Returns:
        List of fully resolved :class:`~pathlib.Path` objects for extracted
        files.

    Raises:
        ValidationError: When a member path would escape *dest_dir*.
        tarfile.TarError: On corrupt or unreadable archives.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _extract_tar_gz_sync,
        archive_path,
        dest_dir,
    )


def _extract_tar_gz_sync(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Synchronous inner implementation of :func:`extract_tar_gz`."""
    extracted: list[Path] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            safe_path = validate_archive_member(member.name, dest_dir)
            if not member.isreg() and not member.isdir():
                continue
            tar.extract(member, path=dest_dir, filter="data")
            if member.isreg():
                extracted.append(safe_path)
    return extracted


def list_tar_gz_members(archive_path: Path) -> list[str]:
    """Return the member names inside *archive_path* without extracting.

    Args:
        archive_path: Path to the ``.tar.gz`` file.

    Returns:
        List of member name strings.
    """
    with tarfile.open(archive_path, "r:gz") as tar:
        return tar.getnames()
