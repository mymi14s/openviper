"""runserver management command."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import concurrent.futures
import importlib
import logging
import os
import shutil
from pathlib import Path

from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import get_banner
from openviper.db.migrations.executor import MigrationExecutor, discover_migrations

logger = logging.getLogger("openviper.runserver")

# Thread pool for background migration check
_MIGRATION_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="migration-check"
)
atexit.register(_MIGRATION_THREAD_POOL.shutdown, wait=False)


def _clear_pycache(root: str | Path = ".") -> None:
    """Delete every ``__pycache__`` directory under *root*."""
    count = 0
    for cache_dir in Path(root).rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
            count += 1
        except OSError:
            pass
    if count:
        logger.debug(
            "Cleared %d __pycache__ director%s before reload",
            count,
            "y" if count == 1 else "ies",
        )


class Command(BaseCommand):
    help = "Start the OpenViper development server using uvicorn."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
        parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
        parser.add_argument(
            "--reload", action="store_true", default=True, help="Enable auto-reload"
        )
        parser.add_argument("--no-reload", dest="reload", action="store_false")
        parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
        parser.add_argument(
            "app",
            nargs="?",
            default=None,
            help="ASGI app path, e.g. myproject.asgi:app (auto-detected from settings)",
        )

    def handle(self, **options):  # type: ignore[override]
        try:
            import uvicorn
        except ImportError:
            self.stderr(self.style_error("uvicorn is required: pip install uvicorn"))
            return

        # ── Start migration check in background (non-blocking) ───────────
        migration_future = _MIGRATION_THREAD_POOL.submit(self._check_pending_migrations)

        app_path = self._resolve_app_path(options)
        host = options["host"]
        port = options["port"]
        reload = options["reload"]
        workers = options.get("workers", 1)

        get_banner(self, host, port)

        # Show migration check result if it completes quickly
        try:
            migration_future.result(timeout=0.5)  # Wait max 0.5s for migration check
        except concurrent.futures.TimeoutError:
            # Migration check is taking longer - let it run in background
            logger.debug("Migration check running in background")
        except Exception:
            # Ignore errors from migration check - server should start anyway
            pass

        if reload:
            self._run_with_cache_clear(uvicorn, app_path, host, port)
        else:
            uvicorn.run(
                app_path,
                host=host,
                port=port,
                reload=False,
                workers=workers,
                log_level="debug",
            )

    # ── helpers ───────────────────────────────────────────────────────

    def _reload_dirs(self, root: str) -> list[str]:
        """Return directories uvicorn should watch for file changes.

        Always includes the project root.  If the ``openviper`` package is a local
        (editable / source-tree) install — i.e. NOT inside a ``site-packages``
        directory — its parent directory is added too so that framework-level
        edits also trigger a reload.
        """
        dirs = [root]
        try:
            import openviper as _openviper_pkg

            pkg_parent = str(Path(_openviper_pkg.__file__).parent.parent.resolve())
            # Only add when it's a dev/source install, not a pip install.
            if "site-packages" not in pkg_parent and pkg_parent not in dirs:
                dirs.append(pkg_parent)
        except Exception:
            pass
        return dirs

    def _run_with_cache_clear(self, uvicorn, app_path: str, host: str, port: int) -> None:
        """Run uvicorn with ``--reload`` and clear ``__pycache__`` before every restart.

        Patches :meth:`uvicorn.supervisors.ChangeReload.restart` (stat-based,
        always present) and :meth:`uvicorn.supervisors.WatchFilesReload.restart`
        (watchfiles-based, optional).  Both are called by uvicorn's reload
        supervisor right before the worker process is restarted.
        """
        root = os.getcwd()
        reload_dirs = self._reload_dirs(root)

        for supervisor_fqn in (
            "uvicorn.supervisors.ChangeReload",
            "uvicorn.supervisors.WatchFilesReload",
        ):
            module_name, class_name = supervisor_fqn.rsplit(".", 1)
            try:
                mod = importlib.import_module(module_name)
                cls = getattr(mod, class_name)
                _orig = cls.restart

                def _patched(self_reloader, _orig=_orig, _root=root):
                    _clear_pycache(_root)
                    _orig(self_reloader)

                cls.restart = _patched  # type: ignore[method-assign]
            except ImportError, AttributeError:
                # Older/newer uvicorn build without this supervisor — ignore.
                pass

        uvicorn.run(
            app_path,
            host=host,
            port=port,
            reload=True,
            reload_dirs=reload_dirs,
            log_level="debug",
        )

    def _resolve_app_path(self, options: dict) -> str:
        """Return the dotted ASGI app path (e.g. ``myproject.asgi:app``)."""
        app_path: str | None = options.get("app")
        if app_path is not None:
            return app_path

        # Auto-detect from OPENVIPER_SETTINGS_MODULE / current directory
        settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
        package = settings_module.split(".")[0] if settings_module else None
        if package:
            return f"{package}.asgi:app"

        cwd_name = os.path.basename(os.getcwd())
        return f"{cwd_name}.asgi:app"

    def _check_pending_migrations(self) -> None:
        """Detect unapplied migrations and print a red warning at startup.

        This runs in a background thread to avoid blocking server startup.
        """
        try:
            from openviper.conf import settings

            resolver = AppResolver()
            installed_apps = getattr(settings, "INSTALLED_APPS", [])
            resolved = resolver.resolve_all_apps(installed_apps)
            resolved_apps = resolved.get("found", {})
            if not isinstance(resolved_apps, dict):
                resolved_apps = {}

            async def _get_pending() -> list[str]:
                executor = MigrationExecutor(resolved_apps=resolved_apps)
                try:
                    await executor._ensure_migration_table()
                    applied = await executor._applied_migrations()
                except Exception:
                    # DB might not exist at all — everything is pending.
                    applied = set()
                all_migrations = discover_migrations(resolved_apps=resolved_apps)
                return [
                    f"{rec.app}.{rec.name}"
                    for rec in all_migrations
                    if (rec.app, rec.name) not in applied
                ]

            pending = asyncio.run(_get_pending())

            if pending:
                self.stdout("")
                self.stdout(
                    self.style_error(
                        "  You have unapplied migrations. Run "
                        "'python viperctl.py migrate' to apply them."
                    )
                )
                self.stdout(self.style_error(f"  Missing migrations: {', '.join(pending)}"))
                self.stdout("")
        except Exception:
            # Never prevent the server from starting because the check failed.
            pass
