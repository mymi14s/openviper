"""Database patch system for one-time data migrations.

Provides the ``@db_patch`` decorator and runner for executing patches
during ``migrate``.
"""

from __future__ import annotations

import typing as t

from openviper.db.patches.decorator import (
    PatchEntry,
    PatchRegistry,
    db_patch,
    get_registry,
    reset_registry,
)
from openviper.db.patches.runner import (
    discover_patches,
    ensure_patch_table,
    get_applied_patches,
    record_patch,
    run_patches,
)

__all__ = [
    "PatchEntry",
    "PatchRegistry",
    "db_patch",
    "discover_patches",
    "ensure_patch_table",
    "get_applied_patches",
    "get_registry",
    "record_patch",
    "reset_registry",
    "run_patches",
]
