"""Utility functions for management commands and CLI."""

from __future__ import annotations

from collections.abc import Mapping

from openviper.core.management.base import BaseCommand


def get_banner(cmd_obj: BaseCommand, host: str, port: int) -> None:
    """Display the startup banner."""
    banner = rf"""

            OOOOO  PPPPP   EEEEE  N   N  V   V  III  PPPPP  EEEEE  RRRR
           O     O P    P  E      NN  N  V   V   I   P    P E      R   R
           O     O PPPPP   EEEE   N N N  V   V   I   PPPPP  EEEE   RRRR
           O     O P       E      N  NN   V v    I   P      E      R  R
            OOOOO  P       EEEEE  N   N    V    III  P      EEEEE  R   R

            OpenViper development server running at http://{host}:{port}/
            Use Ctrl+C to stop.
            """
    cmd_obj.stdout(cmd_obj.style_success(banner))


def print_banner(host: str, port: int, cmd_obj: BaseCommand | None = None) -> None:
    """Print the startup banner to stdout.

    Args:
        host: Server host
        port: Server port
        cmd_obj: Optional command object with .stdout() and .style_success()
    """
    if cmd_obj is None:
        cmd_obj = BaseCommand()

    get_banner(cmd_obj, host, port)


def get_default_database_url(settings_obj: object) -> str:
    """Return the configured default database URL."""
    databases = getattr(settings_obj, "DATABASES", {})
    if isinstance(databases, Mapping):
        default_config = databases.get("default")
        if isinstance(default_config, Mapping):
            url = default_config.get("URL")
            if isinstance(url, str):
                return url

    database_url = getattr(settings_obj, "DATABASE_URL", "")
    if isinstance(database_url, str):
        return database_url
    return ""
