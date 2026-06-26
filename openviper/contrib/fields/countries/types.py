"""Country contrib type aliases."""

from typing import Protocol


class CountryOwner(Protocol):
    """Object that can hold descriptor-backed country values."""

    __dict__: dict[str, object]


type CountryRepresentation = str | dict[str, str] | None
type CountrySchema = dict[str, str | list[str]]
type CacheStats = dict[str, int | None]
type CacheInfoMap = dict[str, CacheStats]
type ExtraCountries = tuple[tuple[str, str, str], ...]
