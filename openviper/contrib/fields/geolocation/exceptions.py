"""Exceptions raised by geolocation contrib."""

from __future__ import annotations


class GeoLocationError(Exception):
    """Base exception for geolocation errors."""


class DependencyMissingError(GeoLocationError, ImportError):
    """Raised when an optional geolocation dependency is not installed."""

    MESSAGE = (
        "The openviper geolocation module requires optional dependencies that are "
        "not installed.\n"
        "Install them with:  pip install openviper[Geolocation]\n"
        "Missing package: {package}"
    )

    def __init__(self, package: str) -> None:
        self.package = package
        super().__init__(self.MESSAGE.format(package=package))


class InvalidPointError(GeoLocationError, ValueError):
    """Raised when a Point is constructed with out-of-range coordinates."""
