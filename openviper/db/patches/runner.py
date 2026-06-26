"""Patch runner that executes registered patches during migrate.

Discovers ``@db_patch`` functions from installed apps' ``patches/``
directories, queries the ``openviper_patches`` table for already-applied
patches, and runs unapplied ones in order.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import typing as t
from pathlib import Path

import sqlalchemy as sa

from openviper.db.connection import get_engine, get_metadata
from openviper.db.connections import connections
from openviper.db.patches.decorator import PatchEntry, get_registry
from openviper.utils import timezone

if t.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("openviper.patches")

PATCH_TABLE_NAME = "openviper_patches"


def get_patch_label(entry: PatchEntry) -> str:
    """Return the console label for a patch entry."""
    return f"{entry.module}.{entry.name}"


def get_phase_title(post_migrate: bool) -> str:
    """Return the human-readable patch phase title."""
    return "Post Migrate Patches" if post_migrate else "Pre Migrate Patches"


def print_patch_line(message: str) -> None:
    """Print a patch runner line to console."""
    print(message)


async def get_async_engine(db_alias: str = "default") -> AsyncEngine:
    """Return the async engine for the given database alias."""
    if db_alias == "default":
        try:
            if connections.initialized and "default" in connections.backends:
                return await connections.get("default").create_engine()
        except Exception:
            logger.debug("Falling back to default engine for patch runner")
    return await get_engine()


def get_patch_table() -> sa.Table:
    """Return or create the patch tracking table definition."""
    meta = get_metadata()
    if PATCH_TABLE_NAME in meta.tables:
        return meta.tables[PATCH_TABLE_NAME]
    return sa.Table(
        PATCH_TABLE_NAME,
        meta,
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "oracle"),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("app", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(10), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            default=timezone.now,
        ),
        sa.UniqueConstraint("app", "name", "phase", name="uq_patch_app_name_phase"),
    )


async def ensure_patch_table(db_alias: str = "default") -> None:
    """Create the patch tracking table if it does not exist."""
    table = get_patch_table()
    engine = await get_async_engine(db_alias)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))


async def get_applied_patches(db_alias: str = "default") -> set[tuple[str, str, str]]:
    """Return the set of (app, name, phase) tuples already applied."""
    await ensure_patch_table(db_alias)
    table = get_patch_table()
    engine = await get_async_engine(db_alias)
    async with engine.connect() as conn:
        result = await conn.execute(sa.select(table.c.app, table.c.name, table.c.phase))
        return {(row.app, row.name, row.phase) for row in result}


async def record_patch(
    app: str,
    name: str,
    phase: str,
    db_alias: str = "default",
) -> None:
    """Record a patch as applied in the tracking table."""
    table = get_patch_table()
    engine = await get_async_engine(db_alias)
    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(table).values(
                app=app,
                name=name,
                phase=phase,
                applied_at=timezone.now(),
            )
        )


def discover_patches(
    resolved_apps: dict[str, str] | None = None,
) -> None:
    """Import all patch modules from installed apps.

    Scans ``<app>/patches/`` directories for ``*.py`` files and imports
    them so that ``@db_patch`` decorators register their functions.
    """
    builtin_apps = ("openviper.auth", "openviper.admin", "openviper.tasks")
    for dotted in builtin_apps:
        try:
            pkg = importlib.import_module(dotted)
        except Exception:
            logger.debug("Skipping unimportable built-in app: %s", dotted)
            continue
        pkg_file = getattr(pkg, "__file__", None)
        if pkg_file is None:
            continue
        pkg_dir = Path(pkg_file).resolve().parent
        patches_dir = pkg_dir / "patches"
        if patches_dir.is_dir():
            import_patch_modules(patches_dir, dotted)

    if resolved_apps:
        for app_name, app_path in resolved_apps.items():
            patches_dir = Path(app_path) / "patches"
            if patches_dir.is_dir():
                import_patch_modules(patches_dir, app_name)


def import_patch_modules(patches_dir: Path, app_name: str) -> None:
    """Import all Python files from a patches directory."""
    for py_file in sorted(patches_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"{app_name}.patches.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            logger.warning("Could not load patch %s: %s", py_file, exc)


async def run_patches(
    post_migrate: bool = True,
    *,
    verbose: bool = False,
    database: str = "default",
) -> list[str]:
    """Run unapplied patches for the given phase.

    Args:
        post_migrate: If True, run post_migrate patches. If False, run
            pre_migrate patches.
        verbose: Print patch names as they run.
        database: Database alias.

    Returns:
        List of applied patch names (``app.name`` format).
    """
    phase = "post" if post_migrate else "pre"
    registry = get_registry()
    patches = registry.get_sorted(post_migrate=post_migrate)

    if not patches:
        return []

    applied_set = await get_applied_patches(db_alias=database)
    applied: list[str] = []
    phase_title = get_phase_title(post_migrate)

    print_patch_line(f"\n{phase_title}\n")

    for entry in patches:
        key = (entry.app, entry.name, phase)
        if key in applied_set:
            continue

        label = get_patch_label(entry)
        print_patch_line(f"Executing {label}")

        docstring = inspect.getdoc(entry.func)
        if docstring:
            print_patch_line(f"Info: {docstring}")

        try:
            await entry.func()
            await record_patch(entry.app, entry.name, phase, db_alias=database)
            applied.append(f"{entry.app}.{entry.name}")
            print_patch_line(f"Success: {label}\n")
        except Exception as exc:
            logger.error("Failed to apply patch %s.%s: %s", entry.app, entry.name, exc)
            raise

    print_patch_line(f"{phase_title} Complete\n")

    return applied
