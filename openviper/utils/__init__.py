"""OpenViper utils package."""

from __future__ import annotations

import importlib
import typing as t

from openviper.utils.importlib import import_string

DATASTRUCTURE_EXPORTS: t.Final[frozenset[str]] = frozenset(
    {
        "Headers",
        "ImmutableMultiDict",
        "MutableHeaders",
        "QueryParams",
    }
)
IMPORTLIB_EXPORTS: t.Final[frozenset[str]] = frozenset({"import_string"})

__all__ = [
    "Headers",
    "MutableHeaders",
    "QueryParams",
    "ImmutableMultiDict",
    "import_string",
]


def __getattr__(name: str) -> object:
    if name in DATASTRUCTURE_EXPORTS:
        module = importlib.import_module("openviper.utils.datastructures")
        return getattr(module, name)

    if name in IMPORTLIB_EXPORTS:
        module = importlib.import_module("openviper.utils.importlib")
        return getattr(module, name)

    raise AttributeError(f"module 'openviper.utils' has no attribute {name!r}")
