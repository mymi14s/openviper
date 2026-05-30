"""Backup metadata creation and reading utilities."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import openviper


def compute_checksum(file_path: Path) -> str:
    """Compute the SHA-256 checksum of *file_path*.

    Args:
        file_path: Path to the file to hash.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    sha256 = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def build_metadata(
    *,
    database_name: str,
    db_engine: str,
    filename: str,
    checksum: str,
) -> dict[str, str]:
    """Construct the metadata dictionary for a backup archive.

    Args:
        database_name: Logical name of the backed-up database.
        db_engine: Short engine identifier (e.g. ``"sqlite"``, ``"postgres"``).
        filename: The archive filename without directory component.
        checksum: SHA-256 hex digest of the archive.

    Returns:
        A dictionary ready to be serialised as ``metadata.json``.
    """
    return {
        "database_name": database_name,
        "db_engine": db_engine,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "filename": filename,
        "openviper_version": getattr(openviper, "__version__", "unknown"),
        "checksum": checksum,
    }


def write_metadata(metadata: dict[str, str], dest: Path) -> None:
    """Serialise *metadata* as JSON and write it to *dest*.

    Args:
        metadata: Dictionary produced by :func:`build_metadata`.
        dest: Target file path (will be created or overwritten).
    """
    dest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def read_metadata(archive_dir: Path) -> dict[str, str]:
    """Read and parse ``metadata.json`` from *archive_dir*.

    Args:
        archive_dir: Directory that contains ``metadata.json``.

    Returns:
        Parsed metadata dictionary.

    Raises:
        FileNotFoundError: When ``metadata.json`` is absent.
        ValueError: When the file contains invalid JSON.
    """
    meta_path = archive_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found in {archive_dir}")
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid metadata.json in {archive_dir}: {exc}") from exc
