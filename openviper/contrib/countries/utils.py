"""Country utility helpers.

All functions operate exclusively on in-memory data — zero database
access, zero external API calls.  All lookups are O(1) via frozenset
or dict hash table.
"""

from __future__ import annotations

import re

from openviper.contrib.countries.cache import get_countries, get_country
from openviper.contrib.countries.data import COUNTRY_CODES, CountryInfo

_ALPHA2_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{2}$")


def validate_country(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
    strict: bool = True,
) -> bool:
    """Return ``True`` if *code* is a valid ISO 3166-1 alpha-2 country code.

    Normalises to uppercase before checking.  When *extra* is provided those
    codes are also considered valid.  When *strict* is ``True`` (default) the
    function returns ``False`` for any value that is not exactly two ASCII
    letters; this prevents long-string denial-of-service inputs.

    Args:
        code: Candidate country code string.
        extra: Additional ``(code, name, dial_code)`` triples to accept.
        strict: Enforce the two-letter format constraint before lookup.

    Returns:
        ``True`` if valid, ``False`` otherwise.
    """
    if not isinstance(code, str):
        return False
    normalised = code.upper()
    if strict and not _ALPHA2_PATTERN.match(normalised):
        return False
    if normalised in COUNTRY_CODES:
        return True
    if extra:
        extra_codes = frozenset(c[0].upper() for c in extra)
        return normalised in extra_codes
    return False


def get_country_name(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> str | None:
    """Return the English country name for *code* or ``None`` if not found.

    Args:
        code: ISO 3166-1 alpha-2 code (case-insensitive).
        extra: Additional country definitions to search.

    Returns:
        Country name string or ``None``.
    """
    normalised = code.upper() if isinstance(code, str) else ""
    info: CountryInfo | None = get_country(normalised)
    if info is not None:
        return info["name"]
    if extra:
        registry = get_countries(extra)
        entry = registry.get(normalised)
        if entry is not None:
            return entry["name"]
    return None


def get_dial_code(
    code: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> str | None:
    """Return the international dialling code for *code* or ``None``.

    Args:
        code: ISO 3166-1 alpha-2 code (case-insensitive).
        extra: Additional country definitions to search.

    Returns:
        Dial code string (e.g. ``"+44"``) or ``None``.
    """
    normalised = code.upper() if isinstance(code, str) else ""
    info: CountryInfo | None = get_country(normalised)
    if info is not None:
        return info["dial_code"]
    if extra:
        registry = get_countries(extra)
        entry = registry.get(normalised)
        if entry is not None:
            return entry["dial_code"]
    return None


def search_country(
    query: str,
    extra: tuple[tuple[str, str, str], ...] = (),
) -> list[dict[str, str]]:
    """Search countries by partial name or exact code match (case-insensitive).

    Returns a list of dicts with ``code``, ``name``, and ``dial_code`` keys,
    sorted alphabetically by name.  An empty list is returned when no match
    is found or when *query* is blank.

    Args:
        query: Search term to match against country name or code.
        extra: Additional country definitions to include in the search.

    Returns:
        List of matching country dicts.
    """
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
