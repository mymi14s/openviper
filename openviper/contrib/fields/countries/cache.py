"""LRU-cached accessors for the country dataset."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from openviper.contrib.fields.countries.data import (
    COUNTRIES,
    COUNTRY_META,
    CountryInfo,
    CountryMeta,
)

if TYPE_CHECKING:
    from openviper.contrib.fields.countries.types import CacheInfoMap, ExtraCountries


@functools.lru_cache(maxsize=1)
def get_countries(extra: ExtraCountries = ()) -> dict[str, CountryInfo]:
    """Return merged country registry, optionally extended with *extra* entries."""
    if not extra:
        return COUNTRIES
    merged: dict[str, CountryInfo] = dict(COUNTRIES)
    for code, name, dial_code in extra:
        merged[code.upper()] = {"name": name, "dial_code": dial_code}
    return merged


@functools.lru_cache(maxsize=4096)
def get_country(code: str) -> CountryInfo | None:
    """Return CountryInfo for *code* or None."""
    return COUNTRIES.get(code.upper())


@functools.lru_cache(maxsize=1)
def get_country_choices(
    extra: ExtraCountries = (),
) -> tuple[tuple[str, str], ...]:
    """Return sorted (code, name) choice pairs."""
    registry = get_countries(extra)
    return tuple(
        sorted(
            ((code, info["name"]) for code, info in registry.items()),
            key=lambda x: x[1],
        )
    )


@functools.lru_cache(maxsize=4096)
def get_country_meta(code: str) -> CountryMeta | None:
    """Return CountryMeta for *code* or None."""
    return COUNTRY_META.get(code.upper())


def invalidate_cache() -> None:
    """Clear all LRU caches."""
    get_countries.cache_clear()
    get_country.cache_clear()
    get_country_choices.cache_clear()
    get_country_meta.cache_clear()


def get_cache_info() -> CacheInfoMap:
    """Return hit/miss statistics per cached function."""
    return {
        "get_countries": get_countries.cache_info()._asdict(),
        "get_country": get_country.cache_info()._asdict(),
        "get_country_choices": get_country_choices.cache_info()._asdict(),
    }
