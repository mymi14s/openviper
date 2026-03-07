"""test management command."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from openviper.core.management.base import BaseCommand


class Command(BaseCommand):
    __test__ = False  # tell pytest not to collect this class
    help = "Run the project test suite using pytest."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "test_labels",
            nargs="*",
            help="Specific test paths/labels to run (passed directly to pytest)",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="count",
            default=0,
            help="Increase verbosity",
        )
        parser.add_argument(
            "--failfast",
            "-x",
            action="store_true",
            help="Stop on first failure",
        )
        parser.add_argument(
            "--keepdb",
            action="store_true",
            help="Preserve test database across runs",
        )

    def handle(self, **options):  # type: ignore[override]

        args = [sys.executable, "-m", "pytest"]

        verbose_count = options.get("verbose", 0)
        if verbose_count > 0:
            args.append("-" + "v" * verbose_count)

        if options.get("failfast"):
            args.append("-x")

        test_labels = options.get("test_labels") or []
        processed_labels = []
        for label in test_labels:
            if ".py:" in label and ".py::" not in label:
                label = label.replace(".py:", ".py::", 1)
            processed_labels.append(label)

        args += processed_labels if processed_labels else ["tests/"]

        self.stdout(f"Running: {' '.join(args)}")
        result = subprocess.run(args, env={**os.environ, "OPENVIPER_ENV": "testing"})
        sys.exit(result.returncode)
