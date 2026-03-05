"""Utility functions for management commands and CLI."""

from __future__ import annotations

import sys


def get_banner(host: str, port: int) -> str:
    """OpenViper startup banner."""
    return rf"""

 OOOOO  PPPPP   EEEEE  N   N  V   V  III  PPPPP  EEEEE  RRRR
O     O P    P  E      NN  N  V   V   I   P    P E      R   R
O     O PPPPP   EEEE   N N N  V   V   I   PPPPP  EEEE   RRRR
O     O P       E      N  NN   V V    I   P      E      R  R
 OOOOO  P       EEEEE  N   N    V    III  P      EEEEE  R   R


            OpenViper development server running at http://{host}:{port}/
            Use Ctrl+C to stop.
"""


def print_banner(host: str, port: int, style_func=None) -> None:
    """Print the startup banner to stdout.

    Args:
        host: Server host
        port: Server port
        style_func: Optional function to wrap the banner in (e.g. style_success)
    """
    banner = get_banner(host, port)
    if style_func:
        banner = style_func(banner)

    sys.stdout.write(banner)
    sys.stdout.flush()
