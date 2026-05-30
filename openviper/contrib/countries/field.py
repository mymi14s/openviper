"""ISO 3166-1 alpha-2 CharField with in-memory validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.contrib.countries.cache import (
    get_countries,
    get_country,
    get_country_choices,
)
from openviper.contrib.countries.country import Country
from openviper.contrib.countries.data import COUNTRY_CODES
from openviper.contrib.countries.utils import (
    get_country_name,
    search_country,
    validate_country,
)
from openviper.db.fields import CharField

if TYPE_CHECKING:
    from openviper.contrib.countries.types import (
        CountryOwner,
        CountryRepresentation,
        CountrySchema,
        ExtraCountries,
    )


class CountryField(CharField):
    """ORM field storing an ISO 3166-1 alpha-2 country code.

    Validation enforces membership in the ISO registry, optionally
    extended with ``extra_countries``.  Set ``strict=False`` to accept
    non-standard code lengths.
    """

    def __init__(
        self,
        extra_countries: ExtraCountries = (),
        strict: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("max_length", 2)
        super().__init__(**kwargs)
        self._column_type = f"CHAR({self.max_length})"
        self.extra_countries: ExtraCountries = extra_countries
        self.strict: bool = strict
        self.valid_codes: frozenset[str] = self.build_valid_codes()

    def build_valid_codes(self) -> frozenset[str]:
        """Build the complete set of accepted codes as a frozenset."""
        if not self.extra_countries:
            return COUNTRY_CODES
        extra_codes = frozenset(c[0].upper() for c in self.extra_countries)
        return COUNTRY_CODES | extra_codes

    def __get__(
        self, obj: CountryOwner | None, objtype: type[object] | None = None
    ) -> CountryField | Country | None:
        """Descriptor: return Country on instance access."""
        if obj is None:
            # Class-level access returns the field descriptor itself.
            return self
        raw = obj.__dict__.get(self.name)
        if raw is None:
            return None
        if isinstance(raw, Country):
            return raw
        return Country(str(raw), self.extra_countries)

    def __set__(self, obj: CountryOwner, value: object) -> None:
        """Store normalised uppercase code."""
        if value is None:
            obj.__dict__[self.name] = None
        else:
            obj.__dict__[self.name] = str(value).upper()

    def to_python(self, value: object) -> Country | None:
        """Normalise value to Country or return None."""
        if value is None:
            return None
        if isinstance(value, Country) and value.extra_countries == self.extra_countries:
            return value
        return Country(str(value), self.extra_countries)

    def to_db(self, value: object) -> str | None:
        """Return normalised uppercase string or None."""
        if value is None:
            return None
        return str(value).upper()

    def validate(self, value: object) -> None:
        """Validate value is a known ISO country code.

        Raises ValueError for null on non-nullable fields,
        excessive length, or unknown codes.
        """
        if value is not None and len(str(value)) > 10:
            raise ValueError("Country code exceeds maximum safe length.")

        if value is None and not self.null:
            raise ValueError(f"Field '{self.name}' cannot be null.")

        super().validate(value)
        if value is None:
            return
        normalised = str(value).upper()
        if not validate_country(normalised, extra=self.extra_countries, strict=self.strict):
            msg = f"'{normalised}' is not a valid ISO 3166-1 alpha-2 country code."
            raise ValueError(msg)

    def get_choices(self) -> tuple[tuple[str, str], ...]:
        """Return (code, name) pairs sorted by name."""
        return get_country_choices(self.extra_countries)

    def get_country_name(self, code: str | None) -> str | None:
        """Return English name for code, or None."""
        if code is None:
            return None
        return get_country_name(code, extra=self.extra_countries)

    def search(self, query: str) -> list[dict[str, str]]:
        """Search countries by partial name or exact code match."""
        return search_country(query, extra=self.extra_countries)

    def to_representation(self, value: str | None, *, full: bool = False) -> CountryRepresentation:
        """Return ISO code string, or dict with code/name/dial_code when full=True."""
        if value is None:
            return None
        normalised = str(value).upper()
        if not full:
            return normalised
        info = get_country(normalised)
        if info is None and self.extra_countries:
            info = get_countries(self.extra_countries).get(normalised)
        if info is None:
            return {"code": normalised, "name": normalised, "dial_code": ""}
        return {
            "code": normalised,
            "name": info["name"],
            "dial_code": info["dial_code"],
        }

    @classmethod
    def openapi_schema(cls, extra_countries: ExtraCountries = ()) -> CountrySchema:
        """Return OpenAPI 3.1 JSON-Schema with enum of valid country codes."""
        codes = list(COUNTRY_CODES)
        if extra_countries:
            codes.extend(c[0].upper() for c in extra_countries)
        codes.sort()
        return {
            "type": "string",
            "enum": codes,
            "description": "ISO 3166-1 alpha-2 country code",
            "pattern": "^[A-Z]{2}$",
            "example": "GB",
        }
