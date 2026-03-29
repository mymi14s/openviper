"""Country value object for ISO 3166-1 alpha-2 attribute access.

Returned by ``CountryField.__get__`` when accessed on a model instance.
Subclasses ``str`` so all existing string comparisons, serialisers, and ORM
filters continue to work without changes.

Example::

    user.country            # Country('GB')
    user.country.iso        # 'GB'
    user.country.name       # 'United Kingdom'
    user.country.dial_code  # '+44'
    user.country.alpha3     # 'GBR'
    user.country.continent  # 'Europe'
    user.country.flag       # '🇬🇧'
    user.country == 'GB'    # True
    str(user.country)       # 'GB'
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from openviper.contrib.countries.cache import get_countries, get_country, get_country_meta

if TYPE_CHECKING:
    from openviper.contrib.countries.data import CountryInfo, CountryMeta

_EXTRA_COUNTRIES_TYPE = tuple[tuple[str, str, str], ...]


class Country(str):
    """An ISO 3166-1 alpha-2 country code that also exposes country metadata.

    Subclasses :class:`str` so the value behaves as a plain string everywhere
    (comparisons, JSON serialisation, ORM filters, string formatting) while
    additionally providing ``.iso``, ``.name``, and ``.dial_code`` attributes.

    Args:
        code: Two-letter uppercase ISO code, e.g. ``'GB'``.
        extra_countries: Optional extra ``(code, name, dial_code)`` triples
            that were registered on the originating :class:`CountryField`.
    """

    _extra: _EXTRA_COUNTRIES_TYPE

    def __new__(
        cls,
        code: str,
        extra_countries: _EXTRA_COUNTRIES_TYPE = (),
    ) -> Country:
        instance = super().__new__(cls, str(code).upper())
        instance._extra = extra_countries
        return instance

    def _resolve_info(self) -> CountryInfo | None:
        """Look up metadata for this code, checking extra_countries as fallback."""
        info = get_country(str(self))
        if info is None and self._extra:
            info = get_countries(self._extra).get(str(self))
        return info

    @property
    def iso(self) -> str:
        """ISO 3166-1 alpha-2 code (same as the string value)."""
        return str(self)

    @property
    def name(self) -> str:
        """English country name, e.g. ``'United Kingdom'``."""
        info = self._resolve_info()
        return info["name"] if info else str(self)

    @property
    def dial_code(self) -> str:
        """International dialling prefix, e.g. ``'+44'``."""
        info = self._resolve_info()
        return info["dial_code"] if info else ""

    @property
    def is_valid(self) -> bool:
        """``True`` if the code resolves to a known country."""
        return self._resolve_info() is not None

    @property
    def flag(self) -> str:
        """Regional indicator emoji for this country (e.g. ``'🇬🇧'``)."""
        code = str(self)
        if len(code) != 2:
            return ""
        return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)

    @cached_property
    def _meta(self) -> CountryMeta | None:
        """Extended metadata from COUNTRY_META, cached per instance."""
        return get_country_meta(str(self))

    @cached_property
    def alpha3(self) -> str:
        """ISO 3166-1 alpha-3 code, e.g. ``'GBR'``."""
        return self._meta["alpha3"] if self._meta else ""

    @cached_property
    def numeric(self) -> str:
        """ISO 3166-1 numeric code (zero-padded string), e.g. ``'826'``."""
        return self._meta["numeric"] if self._meta else ""

    @cached_property
    def continent(self) -> str:
        """Continent name, e.g. ``'Europe'``."""
        return self._meta["continent"] if self._meta else ""

    @cached_property
    def region(self) -> str:
        """UN sub-region, e.g. ``'Northern Europe'``."""
        return self._meta["region"] if self._meta else ""

    @cached_property
    def capital(self) -> str:
        """Capital city name, e.g. ``'London'``."""
        return self._meta["capital"] if self._meta else ""

    @cached_property
    def currency_code(self) -> str:
        """ISO 4217 currency code, e.g. ``'GBP'``."""
        return self._meta["currency_code"] if self._meta else ""

    @cached_property
    def currency_name(self) -> str:
        """Currency name, e.g. ``'British Pound'``."""
        return self._meta["currency_name"] if self._meta else ""

    @cached_property
    def currency_symbol(self) -> str:
        """Currency symbol, e.g. ``'£'``."""
        return self._meta["currency_symbol"] if self._meta else ""

    @cached_property
    def languages(self) -> list[str]:
        """BCP-47 language tags spoken in this country, e.g. ``['en']``."""
        return list(self._meta["languages"]) if self._meta else []

    @cached_property
    def tld(self) -> str:
        """Country-code top-level domain, e.g. ``'.gb'``."""
        return self._meta["tld"] if self._meta else ""

    @cached_property
    def is_eu(self) -> bool:
        """``True`` if the country is an EU member state."""
        return bool(self._meta["is_eu"]) if self._meta else False

    @cached_property
    def is_eea(self) -> bool:
        """``True`` if the country is in the European Economic Area."""
        return bool(self._meta["is_eea"]) if self._meta else False

    @cached_property
    def timezone(self) -> str:
        """Primary IANA timezone identifier, e.g. ``'Europe/London'``."""
        return self._meta["timezone"] if self._meta else ""

    def __repr__(self) -> str:
        return f"Country('{str(self)}')"

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickling support — restores as a plain ``Country`` (no extra_countries)."""
        return (Country, (str(self), self._extra))
