"""Utility functions for management commands and CLI."""

from __future__ import annotations

from typing import Any

from openviper.core.management.base import BaseCommand


def get_banner(cmd_obj: Any, host: str, port: int) -> None:
    """Display the startup banner."""
    cmd_obj.stdout(cmd_obj.style_success(rf"""

            OOOOO  PPPPP   EEEEE  N   N  V   V  III  PPPPP  EEEEE  RRRR
           O     O P    P  E      NN  N  V   V   I   P    P E      R   R
           O     O PPPPP   EEEE   N N N  V   V   I   PPPPP  EEEE   RRRR
           O     O P       E      N  NN   V v    I   P      E      R  R
            OOOOO  P       EEEEE  N   N    V    III  P      EEEEE  R   R


            OpenViper development server running at http://{host}:{port}/
            Use Ctrl+C to stop.
            """))


def print_banner(host: str, port: int, cmd_obj: Any = None) -> None:
    """Print the startup banner to stdout.

    Args:
        host: Server host
        port: Server port
        cmd_obj: Optional command object with .stdout() and .style_success()
    """
    if cmd_obj is None:
        cmd_obj = BaseCommand()

    get_banner(cmd_obj, host, port)
