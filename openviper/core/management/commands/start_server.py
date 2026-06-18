"""start-server management command."""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import importlib
import logging
import os
import shutil
from pathlib import Path

from openviper.conf import settings
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import get_banner, resolve_installed_apps, run_async_command
from openviper.db.migrations.executor import MigrationExecutor, discover_migrations
from openviper.utils.logging import get_uvicorn_log_config

try:
    import uvicorn
except ImportError:  # pragma: no cover
    uvicorn = None  # type: ignore[assignment]

try:
    import openviper as openviper_pkg
except Exception:  # pragma: no cover
    openviper_pkg = None  # type: ignore[assignment]

logger = logging.getLogger("openviper.start-server")

LEVEL_RANK: dict[str, int] = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}

MIGRATION_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="migration-check"
)
atexit.register(MIGRATION_THREAD_POOL.shutdown, wait=False)


def clear_pycache(root: str | Path = ".") -> None:
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

    def handle(self, **options) -> None:  # type: ignore[override]
        if uvicorn is None:
            self.stderr(self.style_error("uvicorn is required: pip install uvicorn"))
            return

        migration_future = MIGRATION_THREAD_POOL.submit(self.check_pending_migrations)

        app_path = self.resolve_app_path(options)
        host = options["host"]
        port = options["port"]
        reload = options["reload"]
        workers = options.get("workers", 1)

        settings_level = getattr(settings, "LOG_LEVEL", "INFO").lower()
        log_level = settings_level if LEVEL_RANK.get(settings_level, 1) <= 1 else "info"

        get_banner(self, host, port)

        try:
            migration_future.result(timeout=0.5)
        except concurrent.futures.TimeoutError:
            logger.debug("Migration check running in background")
        except Exception:
            pass

        log_config = get_uvicorn_log_config()

        if reload:
            self.run_with_cache_clear(uvicorn, app_path, host, port, log_level, log_config)
        else:
            uvicorn.run(
                app_path,
                host=host,
                port=port,
                reload=False,
                workers=workers,
                log_level=log_level,
                log_config=log_config,
            )

    def reload_dirs(self, root: str) -> list[str]:
        """Return directories uvicorn should watch for file changes.

        Always includes the project root.  If the ``openviper`` package is a local
        (editable / source-tree) install - i.e. NOT inside a ``site-packages``
        directory - its parent directory is added too so that framework-level
        edits also trigger a reload.
        """
        dirs = [root]
        if openviper_pkg is not None:
            pkg_parent = str(Path(openviper_pkg.__file__).parent.parent.resolve())
            if "site-packages" not in pkg_parent and pkg_parent not in dirs:
                dirs.append(pkg_parent)
        return dirs

    def run_with_cache_clear(
        self,
        uvicorn,
        app_path: str,
        host: str,
        port: int,
        log_level: str = "info",
        log_config: dict | None = None,
    ) -> None:
        """Run uvicorn with ``--reload`` and clear ``__pycache__`` before every restart.

        Patches :meth:`uvicorn.supervisors.ChangeReload.restart` (stat-based,
        always present) and :meth:`uvicorn.supervisors.WatchFilesReload.restart`
        (watchfiles-based, optional).  Both are called by uvicorn's reload
        supervisor right before the worker process is restarted.
        """
        root = os.getcwd()
        reload_dirs = self.reload_dirs(root)

        for supervisor_fqn in (
            "uvicorn.supervisors.ChangeReload",
            "uvicorn.supervisors.WatchFilesReload",
        ):
            module_name, class_name = supervisor_fqn.rsplit(".", 1)
            try:
                mod = importlib.import_module(module_name)
                cls = getattr(mod, class_name)
                original_restart = cls.restart

                def patched_restart(
                    self_reloader,
                    original_restart=original_restart,
                    _root=root,
                    _cls=cls,
                ):
                    clear_pycache(_root)
                    if not isinstance(self_reloader, _cls):
                        return
                    original_restart(self_reloader)

                cls.restart = patched_restart  # type: ignore[method-assign]
            except (ImportError, AttributeError):
                pass

        uvicorn.run(
            app_path,
            host=host,
            port=port,
            reload=True,
            reload_dirs=reload_dirs,
            log_level=log_level,
            log_config=log_config,
        )

    def resolve_app_path(self, options: dict) -> str:
        """Return the dotted ASGI app path (e.g. ``myproject.asgi:app``)."""
        app_path: str | None = options.get("app")
        if app_path is not None:
            return app_path

        settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
        package = settings_module.split(".")[0] if settings_module else None

        if package:
            try:
                pkg_module = importlib.import_module(package)
                has_file = hasattr(pkg_module, "__file__") and pkg_module.__file__
                pkg_dir = Path(pkg_module.__file__).parent if has_file else None
            except ImportError:
                pkg_dir = None

            if pkg_dir is not None:
                if (pkg_dir / "asgi.py").is_file():
                    return f"{package}.asgi:app"
                if (pkg_dir / "app.py").is_file():
                    return f"{package}.app:app"

            return f"{package}.asgi:app"

        cwd_name = os.path.basename(os.getcwd())
        return f"{cwd_name}.asgi:app"

    def check_pending_migrations(self) -> None:
        """Detect unapplied migrations and print a red warning at startup.

        This runs in a background thread to avoid blocking server startup.
        """
        try:
            resolver, resolved_apps = resolve_installed_apps()
            if not isinstance(resolved_apps, dict):
                resolved_apps = {}

            async def get_pending() -> list[str]:
                executor = MigrationExecutor(resolved_apps=resolved_apps)
                try:
                    await executor.ensure_migration_table()
                    applied = await executor.applied_migrations()
                except Exception:
                    # Fresh or missing database - treat all migrations as pending.
                    applied = set()
                all_migrations = discover_migrations(resolved_apps=resolved_apps)
                return [
                    f"{rec.app}.{rec.name}"
                    for rec in all_migrations
                    if (rec.app, rec.name) not in applied
                ]

            pending = run_async_command(get_pending())

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
            pass
