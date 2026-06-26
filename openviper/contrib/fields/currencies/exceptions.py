"""Exceptions raised by currencies contrib."""

from __future__ import annotations


class CurrenciesError(Exception):
    """Base exception for currencies errors."""


class DependencyMissingError(CurrenciesError, ImportError):
    """Raised when an optional currencies dependency is not installed."""

    MESSAGE = (
        "The openviper currencies module requires optional dependencies that "
        "are not installed.\n"
        "Install them with:  pip install openviper[currencies]\n"
        "Missing package: {package}"
    )

    def __init__(self, package: str) -> None:
        self.package = package
        super().__init__(self.MESSAGE.format(package=package))


class CurrencyValidationError(CurrenciesError, ValueError):
    """Raised when a currency code fails validation."""
