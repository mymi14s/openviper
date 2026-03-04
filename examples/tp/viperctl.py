#!/usr/bin/env python
"""OpenViper viperctl.py for tp."""

import os
import sys

import openviper
from openviper.core.management import execute_from_command_line


def main() -> None:
    os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "tp.settings")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    openviper.setup(force=True)
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
