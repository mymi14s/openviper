#!/usr/bin/env python
"""OpenViper viperctl.py for ai_moderation_platform."""

import sys

from openviper.core.management import execute_from_command_line


def main() -> None:
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
