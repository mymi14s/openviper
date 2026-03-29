"""Lazy-loading cache for the country dataset.

All public functions are decorated with ``functools.lru_cache`` so that
the country data is assembled at most once per process.  The underlying
``COUNTRIES`` dict is imported at the module level; no I/O or network
access is performed at any point.
"""

from __future__ import annotations

import functools
from typing import Any

from openviper.contrib.countries.data import COUNTRIES, COUNTRY_META, CountryInfo, CountryMeta


@functools.lru_cache(maxsize=1)
def get_countries(extra: tuple[tuple[str, str, str], ...] = ()) -> dict[str, CountryInfo]:
    """Return the full country registry, optionally merged with extra entries.

    Args:
        extra: Tuple of ``(code, name, dial_code)`` triples for additional
               countries.  Use a tuple (not a dict) so the argument is
               hashable and the result can be cached.

    Returns:
        Merged country mapping (base data + extra).
    """
    if not extra:
        return COUNTRIES
    merged: dict[str, CountryInfo] = dict(COUNTRIES)
    for code, name, dial_code in extra:
        merged[code.upper()] = {"name": name, "dial_code": dial_code}
    return merged


@functools.lru_cache(maxsize=4096)
def get_country(code: str) -> CountryInfo | None:
    """Return the ``CountryInfo`` for *code* or ``None`` if not found.

    The lookup is always O(1) (hash table). Result is cached per code.
    """
    return COUNTRIES.get(code.upper())


@functools.lru_cache(maxsize=1)
def get_country_choices(
    extra: tuple[tuple[str, str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Return a sorted tuple of ``(code, name)`` pairs for use in form choices.

    Sorted alphabetically by country name for predictable ordering.
    """
    registry = get_countries(extra)
    return tuple(
        sorted(((code, info["name"]) for code, info in registry.items()), key=lambda x: x[1])
    )


@functools.lru_cache(maxsize=4096)
def get_country_meta(code: str) -> CountryMeta | None:
    """Return the ``CountryMeta`` for *code* or ``None`` if not found."""
    return COUNTRY_META.get(code.upper())


def invalidate_cache() -> None:
    """Clear all cached data.  Primarily intended for testing."""
    get_countries.cache_clear()
    get_country.cache_clear()
    get_country_choices.cache_clear()
    get_country_meta.cache_clear()


def get_cache_info() -> dict[str, Any]:
    """Return hit/miss statistics for each cached function."""
    return {
        "get_countries": get_countries.cache_info()._asdict(),
        "get_country": get_country.cache_info()._asdict(),
        "get_country_choices": get_country_choices.cache_info()._asdict(),
    }
