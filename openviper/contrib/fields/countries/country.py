"""ISO 3166-1 alpha-2 Country value object with metadata access."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from openviper.contrib.fields.countries.cache import (
    get_countries,
    get_country,
    get_country_meta,
)

if TYPE_CHECKING:
    from openviper.contrib.fields.countries.data import CountryInfo, CountryMeta
    from openviper.contrib.fields.countries.types import ExtraCountries


class Country(str):
    """ISO 3166-1 alpha-2 code with metadata properties.

    Subclasses ``str`` for transparent comparison and serialisation.
    """

    extra_countries: ExtraCountries

    def __new__(
        cls,
        code: str,
        extra_countries: ExtraCountries = (),
    ) -> Country:
        instance = super().__new__(cls, str(code).upper())
        instance.extra_countries = extra_countries
        return instance

    def resolve_info(self) -> CountryInfo | None:
        """Look up metadata for this code, checking extra_countries."""
        info = get_country(str(self))
        if info is None and self.extra_countries:
            info = get_countries(self.extra_countries).get(str(self))
        return info

    @property
    def iso(self) -> str:
        """ISO alpha-2 code."""
        return str(self)

    @property
    def name(self) -> str:
        """English country name."""
        info = self.resolve_info()
        return info["name"] if info else str(self)

    @property
    def dial_code(self) -> str:
        """International dialling prefix."""
        info = self.resolve_info()
        return info["dial_code"] if info else ""

    @property
    def is_valid(self) -> bool:
        """Whether the code resolves to a known country."""
        return self.resolve_info() is not None

    @property
    def flag(self) -> str:
        """Regional indicator emoji."""
        code = str(self)
        if len(code) != 2 or not code.isalpha():
            return ""
        return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)

    @cached_property
    def meta(self) -> CountryMeta | None:
        """Extended metadata from COUNTRY_META."""
        return get_country_meta(str(self))

    @cached_property
    def alpha3(self) -> str:
        """ISO alpha-3 code."""
        return self.meta["alpha3"] if self.meta else ""

    @cached_property
    def numeric(self) -> str:
        """ISO numeric code (zero-padded string)."""
        return self.meta["numeric"] if self.meta else ""

    @cached_property
    def continent(self) -> str:
        """Continent name."""
        return self.meta["continent"] if self.meta else ""

    @cached_property
    def region(self) -> str:
        """UN sub-region."""
        return self.meta["region"] if self.meta else ""

    @cached_property
    def capital(self) -> str:
        """Capital city name."""
        return self.meta["capital"] if self.meta else ""

    @cached_property
    def currency_code(self) -> str:
        """ISO 4217 currency code."""
        return self.meta["currency_code"] if self.meta else ""

    @cached_property
    def currency_name(self) -> str:
        """Currency name."""
        return self.meta["currency_name"] if self.meta else ""

    @cached_property
    def currency_symbol(self) -> str:
        """Currency symbol."""
        return self.meta["currency_symbol"] if self.meta else ""

    @cached_property
    def languages(self) -> list[str]:
        """BCP-47 language tags."""
        return list(self.meta["languages"]) if self.meta else []

    @cached_property
    def tld(self) -> str:
        """Country-code TLD."""
        return self.meta["tld"] if self.meta else ""

    @cached_property
    def is_eu(self) -> bool:
        """EU membership flag."""
        return bool(self.meta["is_eu"]) if self.meta else False

    @cached_property
    def is_eea(self) -> bool:
        """EEA membership flag."""
        return bool(self.meta["is_eea"]) if self.meta else False

    @cached_property
    def timezone(self) -> str:
        """Primary IANA timezone identifier."""
        return self.meta["timezone"] if self.meta else ""

    def __repr__(self) -> str:
        return f"Country('{str(self)}')"

    def __reduce__(self) -> tuple[type[Country], tuple[str, ExtraCountries]]:
        """Pickle support."""
        return (Country, (str(self), self.extra_countries))
