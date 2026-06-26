"""Serializer support for CurrencyField and CurrencyCodeField.

Provides JSON-safe serialization and input coercion for
:class:`~openviper.contrib.fields.currencies.field.CurrencyField`
and :class:`~openviper.contrib.fields.currencies.field.CurrencyCodeField`
values, keeping currency-specific logic inside the currencies package.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from openviper.contrib.fields.currencies.money import Money


def serialize_value(value: Any) -> dict[str, Any] | float | None:
    """Convert a Money or Decimal value to a JSON-safe type.

    ``Money`` objects are serialised as a structured dict with the
    numeric amount and ISO currency code as separate fields, so the
    client can apply locale-aware formatting without parsing a string.

    Plain ``Decimal`` values (from the amount column alone) are
    returned as float.
    """
    if value is None:
        return None
    if isinstance(value, Money):
        return {
            "amount": float(value.amount),
            "currency": value.currency.code,
        }
    if isinstance(value, Decimal):
        return float(value)
    return value


def serialize_amount(value: Any) -> float | None:
    """Serialise just the numeric amount from a Money or Decimal value."""
    if value is None:
        return None
    if isinstance(value, Money):
        return float(value.amount)
    if isinstance(value, Decimal):
        return float(value)
    return float(value) if value is not None else None


def coerce_from_input(value: Any) -> Decimal | None:
    """Coerce incoming input to a Decimal for the amount column."""
    if value is None:
        return None
    if isinstance(value, Money):
        return value.amount
    return Decimal(str(value))


def coerce_code_from_input(value: Any) -> str | None:
    """Normalise a currency code input to uppercase."""
    if value is None:
        return None
    return str(value).upper()
