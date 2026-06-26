"""ISO 4217 currency validation and lookup helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from openviper.contrib.fields.currencies.exceptions import (
    CurrencyValidationError,
    DependencyMissingError,
)

try:
    from babel.numbers import get_currency_symbol as babel_get_currency_symbol
except ImportError:
    babel_get_currency_symbol = None  # type: ignore[assignment]

try:
    from moneyed import CURRENCIES, Currency, get_currency
    from moneyed.classes import CurrencyDoesNotExist
except ImportError as exc:
    raise DependencyMissingError("moneyed") from exc

if TYPE_CHECKING:
    from openviper.contrib.fields.currencies.types import ExtraCurrencies

ALPHA3_PATTERN = re.compile(r"^[A-Z]{3}$")


def validate_currency(
    code: str | None,
    extra: ExtraCurrencies = (),
    strict: bool = True,
) -> bool:
    """Return True when *code* is a recognised ISO 4217 currency code.

    Args:
        code: Uppercase 3-letter currency code (None returns False).
        extra: Additional ``(code, name)`` tuples accepted alongside ISO 4217.
        strict: When False, accept any 3-letter uppercase code not in the registry.
    """
    if code is None:
        return False
    normalised = str(code).upper()
    if not ALPHA3_PATTERN.match(normalised):
        return False
    extra_codes = {c[0].upper() for c in extra}
    if normalised in extra_codes:
        return True
    if normalised in CURRENCIES:
        return True
    if not strict:
        return bool(ALPHA3_PATTERN.match(normalised))
    return False


def get_currency_name(code: str | None, extra: ExtraCurrencies = ()) -> str | None:
    """Return the display name for *code*, or None when unknown."""
    if code is None:
        return None
    normalised = str(code).upper()
    for extra_code, name in extra:
        if extra_code.upper() == normalised:
            return name
    try:
        currency: Currency = get_currency(normalised)
    except CurrencyDoesNotExist:
        return None
    return getattr(currency, "name", None) or normalised


def get_currency_symbol(code: str | None) -> str | None:
    """Return a best-effort symbol for *code* via babel, or None."""
    if code is None:
        return None
    if babel_get_currency_symbol is None:
        return None
    try:
        return cast("str", babel_get_currency_symbol(str(code).upper(), locale="en_US"))
    except (KeyError, ValueError, LookupError):
        return None


def get_currency_choices(extra: ExtraCurrencies = ()) -> tuple[tuple[str, str], ...]:
    """Return ``(code, name)`` pairs for all registered currencies, sorted by name."""
    choices: list[tuple[str, str]] = []
    seen: set[str] = set()
    for code, currency in CURRENCIES.items():
        name = getattr(currency, "name", None) or code
        choices.append((code, name))
        seen.add(code)
    for extra_code, name in extra:
        upper = extra_code.upper()
        if upper not in seen:
            choices.append((upper, name))
            seen.add(upper)
    choices.sort(key=lambda pair: pair[1])
    return tuple(choices)


def search_currency(query: str, extra: ExtraCurrencies = ()) -> list[dict[str, str]]:
    """Search currencies by partial name or exact code match."""
    if not query:
        return []
    needle = query.lower()
    results: list[dict[str, str]] = []
    for code, currency in CURRENCIES.items():
        name = getattr(currency, "name", None) or code
        if code.lower() == needle or needle in name.lower():
            results.append({"code": code, "name": name})
    for extra_code, name in extra:
        upper = extra_code.upper()
        if upper.lower() == needle or needle in name.lower():
            results.append({"code": upper, "name": name})
    results.sort(key=lambda item: item["name"])
    return results


def resolve_currency(
    code: str,
    extra: ExtraCurrencies = (),
    strict: bool = True,
) -> Currency:
    """Return a resolved Currency instance or raise CurrencyValidationError."""
    if not validate_currency(code, extra=extra, strict=strict):
        raise CurrencyValidationError(f"'{code}' is not a valid ISO 4217 currency code.")
    try:
        return get_currency(str(code).upper())
    except CurrencyDoesNotExist as exc:
        if not strict:
            return Currency(code=str(code).upper())
        raise CurrencyValidationError(str(exc)) from exc


__all__ = [
    "get_currency_choices",
    "get_currency_name",
    "get_currency_symbol",
    "resolve_currency",
    "search_currency",
    "validate_currency",
]
