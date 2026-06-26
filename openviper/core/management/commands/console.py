"""console management command - starts an IPython console with OpenViper context."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from openviper import OpenViper, Request
from openviper.auth import get_user_model
from openviper.conf import settings
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import discover_models_in_module
from openviper.http.response import HTMLResponse, JSONResponse

logger = logging.getLogger("openviper.console")

try:
    from IPython.terminal import embed as ipython_embed

    if not hasattr(ipython_embed, "InteractiveConsoleEmbed"):
        ipython_embed.InteractiveConsoleEmbed = ipython_embed.InteractiveShellEmbed
    INITIAL_INTERACTIVE_SHELL_EMBED = ipython_embed.InteractiveShellEmbed
    INITIAL_INTERACTIVE_CONSOLE_EMBED = ipython_embed.InteractiveConsoleEmbed
except ImportError:
    INITIAL_INTERACTIVE_SHELL_EMBED = None
    INITIAL_INTERACTIVE_CONSOLE_EMBED = None


class Command(BaseCommand):
    help = "Start an IPython console with OpenViper pre-imported."

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

    def discover_models(self) -> dict[str, type]:
        models: dict[str, type] = {}

        for app in getattr(settings, "INSTALLED_APPS", []):
            module_name = f"{app}.models" if not app.endswith(".models") else app
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                logger.debug("Could not import %s: %s", module_name, exc)
                continue

            found_list = discover_models_in_module(module)
            for obj in found_list:
                models[obj.__name__] = obj
            found = len(found_list)

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
            logger.warning("Could not resolve user model for console", exc_info=True)

        return models

    def build_namespace(self, include_models: bool) -> tuple[dict[str, object], list[str]]:
        ns: dict[str, object] = {
            "settings": settings,
            "OpenViper": OpenViper,
            "Request": Request,
            "JSONResponse": JSONResponse,
            "HTMLResponse": HTMLResponse,
        }

        model_names: list[str] = []
        if include_models:
            models = self.discover_models()
            ns.update(models)
            model_names = sorted(models.keys())

        return ns, model_names

    def build_banner(self, model_names: list[str]) -> str:
        version = getattr(importlib.import_module("openviper"), "__version__", "?")
        project = getattr(settings, "PROJECT_NAME", "unknown")
        lines = [
            f"OpenViper {version} - {project}",
        ]
        if model_names:
            lines.append(f"Models  : {', '.join(model_names)}")
        lines.append("Tip     : type 'exit()' or Ctrl-D to quit.")
        return "\n".join(lines) + "\n"

    def handle(self, **options) -> None:  # type: ignore[override]
        self.stdout(self.style_bold("\n# OpenViper console"))
        ns, model_names = self.build_namespace(not options.get("no_models", False))
        banner = self.build_banner(model_names)
        self.stdout("")

        command = options.get("command")
        if command:
            code = compile(command, "<console -c>", "exec")
            exec(code, ns)  # noqa: S102  # pylint: disable=exec-used
            return

        if ipython_embed is None or sys.modules.get("IPython.terminal.embed") is None:
            self.stderr("Error: IPython is required to use the console command.")
            self.stderr("Install it with: pip install ipython")
            raise SystemExit(1)

        pre_imported = ", ".join(n for n in sorted(ns) if n[0].isupper() or n == "settings")
        console_embed = getattr(ipython_embed, "InteractiveConsoleEmbed", None)
        shell_embed = ipython_embed.InteractiveShellEmbed
        embed_cls = shell_embed
        if console_embed is not None and console_embed is not INITIAL_INTERACTIVE_CONSOLE_EMBED:
            embed_cls = console_embed

        console = embed_cls(
            user_ns=ns,
            banner1=banner + f"# Pre-imported: {pre_imported}\n",
            colors="Neutral",
            confirm_exit=False,
        )
        console.autoawait = True
        console.loop_runner = "asyncio"
        console()
