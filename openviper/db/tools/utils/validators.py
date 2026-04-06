"""Input validation helpers for database backup and restore operations."""

from __future__ import annotations

import os
import re
from pathlib import Path

_PATH_TRAVERSAL_RE = re.compile(r"\.\.")

_UNSAFE_SHELL_CHARS_RE = re.compile(r"[;&|`$<>\\\n\r\t\x00]")


class ValidationError(ValueError):
    """Raised when a user-supplied value fails a security or integrity check."""


def validate_backup_path(path: str | Path) -> Path:
    """Resolve and validate *path* as a writable backup directory.

    Raises:
        ValidationError: When the path contains traversal sequences or
            resolves to a filesystem root.
    """
    resolved = Path(path).resolve()

    if str(path) != "." and _PATH_TRAVERSAL_RE.search(str(path)):
        raise ValidationError(f"Path traversal detected in backup path: {path!r}")

    if resolved == resolved.root or str(resolved) == "/":
        raise ValidationError("Backup path must not be the filesystem root.")

    return resolved


def validate_backup_file(file_path: str | Path) -> Path:
    """Validate that *file_path* points to an existing readable backup file.

    Raises:
        ValidationError: When the path is unsafe or the file does not exist.
    """
    resolved = Path(file_path).resolve()

    if _PATH_TRAVERSAL_RE.search(str(file_path)):
        raise ValidationError(f"Path traversal detected in backup file path: {file_path!r}")

    if not resolved.exists():
        raise ValidationError(f"Backup file not found: {resolved}")

    if not resolved.is_file():
        raise ValidationError(f"Backup path is not a regular file: {resolved}")

    if not os.access(resolved, os.R_OK):
        raise ValidationError(f"Backup file is not readable: {resolved}")

    return resolved


def validate_subprocess_arg(value: str, *, label: str = "argument") -> str:
    """Reject subprocess arguments that contain shell meta-characters.

    All subprocess calls use ``asyncio.create_subprocess_exec`` (not
    ``shell=True``), but this extra layer prevents accidental injection of
    dangerous tokens into argument lists.

    Raises:
        ValidationError: When *value* contains unsafe characters.
    """
    if _UNSAFE_SHELL_CHARS_RE.search(value):
        raise ValidationError(f"Unsafe characters detected in subprocess {label}: {value!r}")
    return value


def validate_archive_member(member_name: str, target_dir: Path) -> Path:
    """Ensure a tar archive member resolves inside *target_dir*.

    Prevents path-traversal attacks during extraction (tar-slip / zip-slip).

    Raises:
        ValidationError: When the member would be extracted outside *target_dir*.
    """
    resolved = (target_dir / member_name).resolve()
    try:
        resolved.relative_to(target_dir.resolve())
    except ValueError as exc:
        raise ValidationError(
            f"Archive member escapes extraction directory: {member_name!r}"
        ) from exc
    return resolved
