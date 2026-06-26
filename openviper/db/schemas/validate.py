"""
Validate type changes for safety before writing JSON schema files.
Catches dangerous conversions (e.g., Integer to String) at
``makemigrations`` time rather than failing at ``migrate`` time.
"""

from __future__ import annotations

import re
import warnings

from openviper.exceptions import MigrationError


def normalize_type(col_type: str) -> str:
    """Extract the base type name, uppercased, without length suffix."""
    match = re.match(r"^([A-Z_]+)", col_type.strip().upper())
    return match.group(1) if match else col_type.upper()


_INCOMPATIBLE_CHANGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("INTEGER", "STRING"),
        ("INTEGER", "VARCHAR"),
        ("INTEGER", "TEXT"),
        ("STRING", "INTEGER"),
        ("VARCHAR", "INTEGER"),
        ("TEXT", "INTEGER"),
        ("DATETIME", "DATE"),
        ("INTEGER", "BOOLEAN"),
        ("FLOAT", "INTEGER"),
    }
)

_NARROWING_TYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("TEXT", "VARCHAR"),
        ("VARCHAR", "STRING"),
    }
)


def is_narrowing(old_type: str, new_type: str) -> bool:
    """Return True if the new type is narrower than the old type."""
    old_base = normalize_type(old_type)
    new_base = normalize_type(new_type)
    if (old_base, new_base) in _NARROWING_TYPES:
        return True

    old_match = re.match(r"^[A-Z]+\((\d+)\)$", old_type.strip().upper())
    new_match = re.match(r"^[A-Z]+\((\d+)\)$", new_type.strip().upper())
    if old_match and new_match and old_base == new_base:
        old_len = int(old_match.group(1))
        new_len = int(new_match.group(1))
        return new_len < old_len
    return False


def validate_type_change(old_type: str, new_type: str, *, force: bool = False) -> None:
    """Validate that a column type change is safe.

    Args:
        old_type: Previous column type string.
        new_type: New column type string.
        force: If True, skip the incompatible-type check (still warns
            on narrowing).

    Raises:
        MigrationError: If the type change is incompatible and force
            is False.
    """
    old_base = normalize_type(old_type)
    new_base = normalize_type(new_type)

    if not force and (old_base, new_base) in _INCOMPATIBLE_CHANGES:
        raise MigrationError(
            f"Cannot change column type from {old_type} to {new_type}. "
            f"This conversion may cause data loss. "
            f"If intentional, use --force to proceed."
        )

    if is_narrowing(old_type, new_type):
        warnings.warn(
            f"Column type change {old_type} -> {new_type} is narrowing "
            f"and may truncate existing data.",
            stacklevel=2,
        )
