"""Protocol and type aliases for the currencies contrib field."""

from __future__ import annotations

from typing import Protocol


class MoneyOwner(Protocol):
    """Model instance protocol for the MoneyField descriptor."""

    __dict__: dict[str, object]


CurrencyRepresentation = str | dict[str, str | None] | None
CurrencySchema = dict[str, str | list[str]]
ExtraCurrencies = tuple[tuple[str, str], ...]
FormatOptions = dict[str, object]


__all__ = [
    "CurrencyRepresentation",
    "CurrencySchema",
    "ExtraCurrencies",
    "FormatOptions",
    "MoneyOwner",
]
