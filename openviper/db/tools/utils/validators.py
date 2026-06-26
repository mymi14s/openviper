"""Input validation helpers for database backup and restore operations."""

from __future__ import annotations

import os
import re
from pathlib import Path

_PATH_TRAVERSAL_RE = re.compile(r"\.\.|\x00")
_UNSAFE_SHELL_CHARS_RE = re.compile(r"[;&|`$<>\\\n\r\t\x00]")


class ValidationError(ValueError):
    """Raised when a user-supplied value fails a security or integrity check."""


def validate_backup_path(path: str | Path) -> Path:
    """Resolve and validate *path* as a writable backup directory.

    Raises:
        ValidationError: When the path contains traversal sequences, null
            bytes, or resolves to a filesystem root.
    """
    path_str = str(path)
    # Reject null bytes and path traversal before resolve() to prevent
    # ValueError from pathlib and directory traversal attacks.
    if "\x00" in path_str:
        raise ValidationError(f"Null byte detected in backup path: {path_str!r}")
    if path_str != "." and _PATH_TRAVERSAL_RE.search(path_str):
        raise ValidationError(f"Path traversal detected in backup path: {path_str!r}")

    resolved = Path(path).resolve()

    if resolved == resolved.root or str(resolved) == "/":
        raise ValidationError("Backup path must not be the filesystem root.")

    return resolved


def validate_backup_file(file_path: str | Path) -> Path:
    """Validate that *file_path* points to an existing readable backup file.

    Raises:
        ValidationError: When the path is unsafe or the file does not exist.
    """
    path_str = str(file_path)
    # Reject null bytes before resolve() to prevent ValueError from pathlib.
    if "\x00" in path_str:
        raise ValidationError(f"Null byte detected in backup file path: {path_str!r}")
    if _PATH_TRAVERSAL_RE.search(path_str):
        raise ValidationError(f"Path traversal detected in backup file path: {path_str!r}")

    resolved = Path(file_path).resolve()

    if not resolved.exists():
        raise ValidationError(f"Backup file not found: {resolved}")

    if not resolved.is_file():
        raise ValidationError(f"Backup path is not a regular file: {resolved}")

    if not os.access(resolved, os.R_OK):
        raise ValidationError(f"Backup file is not readable: {resolved}")

    return resolved


def validate_subprocess_arg(value: str, *, label: str = "argument") -> str:
    """Reject subprocess arguments that contain console meta-characters.

    All subprocess calls use ``asyncio.create_subprocess_exec`` (not
    ``console=True``), but this extra layer prevents accidental injection of
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
    Also rejects null bytes in member names which can be used to bypass
    path validation on some platforms.

    Raises:
        ValidationError: When the member would be extracted outside *target_dir*.
    """
    if "\x00" in member_name:
        raise ValidationError(f"Archive member contains null byte: {member_name!r}")
    resolved = (target_dir / member_name).resolve()
    try:
        resolved.relative_to(target_dir.resolve())
    except ValueError as exc:
        raise ValidationError(
            f"Archive member escapes extraction directory: {member_name!r}"
        ) from exc
    return resolved
