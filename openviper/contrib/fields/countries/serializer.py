"""Serializer support for CountryField.

Provides JSON-safe serialization and input coercion for
:class:`~openviper.contrib.fields.countries.field.CountryField`
values, keeping country-specific logic inside the countries package.
"""

from __future__ import annotations

from typing import Any

from openviper.contrib.fields.countries.country import Country


def serialize_value(value: Any) -> str | None:
    """Convert a Country value to a JSON-safe string.

    ``Country`` is a ``str`` subclass so this is a passthrough,
    but the explicit function keeps the contract uniform with
    other contrib serializer modules.
    """
    if value is None:
        return None
    if isinstance(value, Country):
        return str(value)
    return str(value).upper() if value is not None else None


def coerce_from_input(value: Any) -> str | None:
    """Normalise incoming input to an uppercase country code string."""
    if value is None:
        return None
    return str(value).upper()
