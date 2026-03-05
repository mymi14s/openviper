"""shell management command — starts an IPython shell with OpenViper context."""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging

from openviper import OpenViper, Request
from openviper.auth import get_user_model
from openviper.conf import settings
from openviper.core.management.base import BaseCommand
from openviper.db.models import Model
from openviper.http.response import HTMLResponse, JSONResponse

logger = logging.getLogger("openviper.shell")


class Command(BaseCommand):
    help = "Start an IPython shell with OpenViper pre-imported."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--no-models",
            action="store_true",
            help="Don't auto-import models from INSTALLED_APPS",
        )
        parser.add_argument(
            "-c",
            "--command",
            help="Execute the given command string and exit",
        )

    def _discover_models(self) -> dict[str, type]:
        models: dict[str, type] = {}

        for app in getattr(settings, "INSTALLED_APPS", []):
            module_name = f"{app}.models" if not app.endswith(".models") else app
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                logger.debug("Could not import %s: %s", module_name, exc)
                continue

            found = 0
            for name, obj in inspect.getmembers(module, inspect.isclass):
                try:
                    if (
                        issubclass(obj, Model)
                        and obj is not Model
                        and obj.__module__ == module.__name__
                    ):
                        models[name] = obj
                        found += 1
                except TypeError:
                    continue

            if found:
                self.stdout(
                    f"  {self.style_success('✓')} {found} model(s)"
                    f" from {self.style_bold(module_name)}"
                )

        try:
            user_cls = get_user_model()
            if user_cls.__name__ not in models:
                models[user_cls.__name__] = user_cls
                self.stdout(
                    f"  {self.style_success('✓')} User model: {self.style_bold(user_cls.__name__)}"
                )
        except Exception:
            pass

        return models

    def _build_namespace(self, include_models: bool) -> tuple[dict[str, object], list[str]]:
        ns: dict[str, object] = {
            "settings": settings,
            "OpenViper": OpenViper,
            "Request": Request,
            "JSONResponse": JSONResponse,
            "HTMLResponse": HTMLResponse,
        }

        model_names: list[str] = []
        if include_models:
            models = self._discover_models()
            ns.update(models)
            model_names = sorted(models.keys())

        return ns, model_names

    def _build_banner(self, model_names: list[str]) -> str:
        version = getattr(importlib.import_module("openviper"), "__version__", "?")
        project = getattr(settings, "PROJECT_NAME", "unknown")
        lines = [
            f"OpenViper {version} — {project}",
        ]
        if model_names:
            lines.append(f"Models  : {', '.join(model_names)}")
        lines.append("Tip     : type 'exit()' or Ctrl-D to quit.")
        return "\n".join(lines) + "\n"

    def handle(self, **options) -> None:  # type: ignore[override]
        self.stdout(self.style_bold("\n# OpenViper Shell"))
        ns, model_names = self._build_namespace(not options.get("no_models", False))
        banner = self._build_banner(model_names)
        self.stdout("")

        command = options.get("command")
        if command:
            exec(command, ns)  # noqa: S102
            return

        try:
            from IPython import embed
            from traitlets.config import Config
        except ImportError as exc:
            raise SystemExit(f"IPython is required but failed to import: {exc}") from exc

        cfg = Config()
        cfg.InteractiveShell.confirm_exit = False
        cfg.InteractiveShell.autoawait = True

        pre_imported = ", ".join(n for n in sorted(ns) if n[0].isupper() or n == "settings")
        embed(
            user_ns=ns,
            banner1=banner + f"# Pre-imported: {pre_imported}\n",
            config=cfg,
            colors="Neutral",
            using="asyncio",
        )
