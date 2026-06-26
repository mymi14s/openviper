"""start-worker management command - unified task worker and scheduler runtime.

Validates ``settings.TASKS``, initialises logging, discovers app task
modules, synchronises periodic schedules, and starts the worker process.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import typing as t

from openviper.conf import settings
from openviper.core.management.base import BaseCommand
from openviper.tasks.conf import validate_tasks_config
from openviper.tasks.runner import run


class Command(BaseCommand):
    """Start the OpenViper background task worker.

    Consolidates both the Cron Scheduler engine and the Async Task
    Worker pool into a single command process architecture.
    """

    help = "Start the OpenViper background task worker and scheduler"

    aliases = ["start-worker"]

    def add_arguments(self, parser: t.Any) -> None:
        parser.add_argument(
            "--modules",
            nargs="*",
            default=[],
            help="Additional Python modules to import before starting",
        )
        parser.add_argument(
            "--queues",
            nargs="*",
            default=None,
            help="Specific queues to consume (default: all)",
        )
        parser.add_argument(
            "--threads",
            type=int,
            default=8,
            help="Number of threads per worker process (default: 8)",
        )
        parser.add_argument(
            "--processes",
            type=int,
            default=1,
            help="Number of worker processes (default: 1)",
        )
        parser.add_argument(
            "--no-scheduler",
            action="store_true",
            default=False,
            help="Disable the periodic scheduler (run on only one worker)",
        )

    def handle(self, **options: t.Any) -> None:
        modules = options.get("modules", [])
        queues = options.get("queues")
        threads = options.get("threads", 8)
        processes = options.get("processes", 1)
        no_scheduler = options.get("no_scheduler", False)

        if importlib.util.find_spec("dramatiq") is None:
            sys.stderr.write(
                "Error: dramatiq is required to run the worker.\n"
                "Install it with: pip install 'openviper[tasks]'\n"
            )
            sys.exit(1)

        cfg = settings.TASKS
        if not isinstance(cfg, dict):
            cfg = {}

        try:
            validate_tasks_config(cfg)
        except Exception as exc:
            sys.stderr.write(f"Error: {exc}\n")
            sys.exit(1)

        for module_name in modules:
            try:
                importlib.import_module(module_name)
            except ImportError:
                sys.stderr.write(f"Error: Could not import module '{module_name}'\n")
                sys.exit(1)

        run(
            processes=processes,
            threads=threads,
            queues=queues,
            no_scheduler=no_scheduler,
        )
