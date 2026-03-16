"""runworker management command — start background task worker.

Runs the task worker.  For database brokers the worker runs entirely
in-process.  For Redis/RabbitMQ brokers, the standard ``dramatiq`` CLI
is invoked as a subprocess with auto-discovered task modules.

Usage::

    python viperctl.py runworker
    python viperctl.py runworker myapp.tasks --threads 4 --queues default high
    python viperctl.py runworker --processes 2 --threads 4
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys

from openviper.conf import settings
from openviper.core.app_resolver import AppResolver
from openviper.core.management.base import BaseCommand
from openviper.tasks.worker import run_worker

logger = logging.getLogger("openviper.tasks")

_SKIP_DIRS: frozenset[str] = frozenset(
    {"migrations", "tests", "__pycache__", ".git", "static", "templates"}
)
_SKIP_FILES: frozenset[str] = frozenset(
    {
        # Project configuration
        "asgi.py",
        "wsgi.py",
        "settings.py",
        "routes.py",
        "urls.py",
        # Framework layer files — rarely contain task definitions
        "models.py",
        "views.py",
        "admin.py",
        "serializers.py",
        "decorators.py",
        "forms.py",
        "filters.py",
        "permissions.py",
        "pagination.py",
        "signals.py",
        "apps.py",
        "validators.py",
    }
)


class Command(BaseCommand):
    help = "Start a Dramatiq task worker."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "modules",
            nargs="*",
            help=(
                "Extra Python module paths containing task definitions "
                "(e.g. myapp.tasks).  Auto-discovery runs regardless."
            ),
        )
        parser.add_argument(
            "--queues",
            "-Q",
            nargs="*",
            default=None,
            help="Only process messages from these queues.",
        )
        parser.add_argument(
            "--threads",
            "-t",
            type=int,
            default=8,
            help="Number of worker threads per process (default: 8).",
        )
        parser.add_argument(
            "--processes",
            "-p",
            type=int,
            default=1,
            help="Number of worker processes (default: 1).",
        )

    def handle(self, **options) -> None:  # type: ignore[override]
        try:
            import dramatiq  # noqa: F401
        except ImportError:
            self.stderr(self.style_error("dramatiq is required: pip install 'openviper[tasks]'"))
            sys.exit(1)

        task_cfg: dict = dict(getattr(settings, "TASKS", {}) or {})
        broker_type: str = task_cfg.get("broker", "redis").lower()

        # Database broker: run in-process (no subprocess needed).
        if broker_type == "database":
            self.stdout("Starting in-process database worker...")
            run_worker(
                processes=options["processes"],
                threads=options["threads"],
                queues=options["queues"],
            )
            return

        # Redis / RabbitMQ: invoke the standard dramatiq CLI as a subprocess.
        # First collect task modules via auto-discovery + any explicit args.
        modules: list[str] = list(options.get("modules") or [])

        resolver = AppResolver()
        for app_name in getattr(settings, "INSTALLED_APPS", []):
            if app_name.startswith("openviper."):
                continue
            app_path, found = resolver.resolve_app(app_name)
            if not (found and app_path):
                continue
            for root, dirs, files in os.walk(app_path):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for filename in files:
                    if (
                        not filename.endswith(".py")
                        or filename in _SKIP_FILES
                        or filename == "__init__.py"
                    ):
                        continue
                    rel = os.path.relpath(os.path.join(root, filename), app_path)
                    modules.append(f"{app_name}.{rel[:-3].replace(os.sep, '.')}")

        if not modules:
            self.stdout("No task modules found. Exiting.")
            sys.exit(1)

        cmd: list[str] = ["dramatiq"] + ["openviper.tasks", "openviper.core.email.queue"] + modules
        cmd += ["--processes", str(options["processes"])]
        cmd += ["--threads", str(options["threads"])]
        if options.get("queues"):
            cmd += ["--queues"] + list(options["queues"])

        self.stdout(f"Starting Dramatiq worker: {' '.join(cmd)}")
        # Pass OPENVIPER_WORKER=1 so the subprocess configures logging and
        # runs SchedulerMiddleware (which starts @periodic tasks after boot).
        env = {**os.environ, "OPENVIPER_WORKER": "1"}
        proc = subprocess.Popen(cmd, env=env)  # pylint: disable=consider-using-with
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.returncode:
            sys.exit(proc.returncode)
