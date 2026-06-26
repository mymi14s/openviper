"""ISO 4217 currency field support for openviper ORM.

Provides CurrencyField - a composite field storing a NUMERIC amount and
a CHAR(3) ISO 4217 currency code, enabling native SQL aggregation
(SUM, AVG) and model-level Money arithmetic.
"""

from __future__ import annotations

from openviper.contrib.fields.currencies.amount_in_words import convert_amount_to_words
from openviper.contrib.fields.currencies.exceptions import (
    CurrenciesError,
    CurrencyValidationError,
)
from openviper.contrib.fields.currencies.exceptions import (
    DependencyMissingError as CurrencyDependencyMissingError,
)
from openviper.contrib.fields.currencies.field import (
    DEFAULT_DECIMAL_PLACES,
    DEFAULT_MAX_DIGITS,
    CurrencyCodeField,
    CurrencyField,
    get_currency_field_name,
)
from openviper.contrib.fields.currencies.money import Currency, Money
from openviper.contrib.fields.currencies.serializer import serialize_value as _serialize_money
from openviper.contrib.fields.currencies.utils import (
    get_currency_choices,
    get_currency_name,
    get_currency_symbol,
    resolve_currency,
    search_currency,
    validate_currency,
)
from openviper.serializers.base import register_contrib_serializer

register_contrib_serializer("Money", _serialize_money)

__all__ = [
    "Currency",
    "CurrencyCodeField",
    "CurrencyDependencyMissingError",
    "CurrencyField",
    "CurrencyValidationError",
    "CurrenciesError",
    "DEFAULT_DECIMAL_PLACES",
    "DEFAULT_MAX_DIGITS",
    "Money",
    "convert_amount_to_words",
    "get_currency_choices",
    "get_currency_field_name",
    "get_currency_name",
    "get_currency_symbol",
    "resolve_currency",
    "search_currency",
    "validate_currency",
]
