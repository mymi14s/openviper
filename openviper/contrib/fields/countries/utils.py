"""Country validation and lookup utilities."""

from __future__ import annotations

import re
import typing as t

from openviper.contrib.fields.countries.cache import get_countries, get_country
from openviper.contrib.fields.countries.data import COUNTRY_CODES, CountryInfo

ALPHA2_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{2}$")

type FieldName = t.Literal["name", "dial_code"]


def validate_country(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
    strict: bool = True,
) -> bool:
    """Return True if code is a valid ISO 3166-1 alpha-2 code.

    When strict, rejects non-two-letter values.
    """
    if not isinstance(code, str):
        return False
    normalised = code.upper()
    if strict and not ALPHA2_PATTERN.match(normalised):
        return False
    if normalised in COUNTRY_CODES:
        return True
    if extra:
        extra_codes = frozenset(c[0].upper() for c in extra)
        return normalised in extra_codes
    return False


def lookup_country_field(
    code: str,
    field: FieldName,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> str | None:
    """Return a specific field from CountryInfo for code, falling back to extras."""
    normalised = code.upper() if isinstance(code, str) else ""
    info: CountryInfo | None = get_country(normalised)
    if info is not None:
        return t.cast("str", info.get(field))
    if extra:
        entry = get_countries(extra).get(normalised)
        if entry is not None:
            return t.cast("str", entry.get(field))
    return None


def get_country_name(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> str | None:
    """Return English country name for code, or None."""
    return lookup_country_field(code, "name", extra)


def get_dial_code(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> str | None:
    """Return international dialling code for code, or None."""
    return lookup_country_field(code, "dial_code", extra)


def search_country(
    query: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> list[dict[str, str]]:
    """Search countries by partial name or exact code match."""
    if not query or not isinstance(query, str):
        return []
    normalised_query = query.strip().lower()
    if not normalised_query:
        return []
    registry = get_countries(extra)
    results: list[dict[str, str]] = []
    for code, info in registry.items():
        if normalised_query in info["name"].lower() or normalised_query == code.lower():
            results.append(
                {
                    "code": code,
                    "name": info["name"],
                    "dial_code": info["dial_code"],
                }
            )
    results.sort(key=lambda x: x["name"])
    return results
