"""Centralised version string for the OpenViper framework.

The single source of truth is ``pyproject.toml``; at runtime the version is
read from the installed package metadata via :mod:`importlib.metadata`.
"""

from importlib.metadata import version as _version

__version__: str = _version("openviper")
