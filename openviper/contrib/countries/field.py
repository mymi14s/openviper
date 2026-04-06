"""CountryField — ISO 3166-1 alpha-2 country code field for OpenViper ORM.

Inherits from ``CharField`` with ``max_length=2``.  All validation is
performed in memory using a frozenset lookup (O(1)); no database calls
are made at any point.

OpenAPI integration: CountryField exposes a ``openapi_schema()`` classmethod
that can be called by the OpenAPI schema generator to produce a proper
``enum`` schema for the field.

Serializer integration: ``to_python()`` always returns a normalised
uppercase code string (or ``None`` for nullable fields).  The field also
provides a ``to_representation()`` helper so serializers may optionally
return the full country object.
"""

from __future__ import annotations

from typing import Any

from openviper.contrib.countries.cache import get_country_choices
from openviper.contrib.countries.country import Country
from openviper.contrib.countries.data import COUNTRY_CODES
from openviper.contrib.countries.utils import validate_country
from openviper.db.fields import CharField

_EXTRA_COUNTRIES_TYPE = tuple[tuple[str, str, str], ...]


class CountryField(CharField):
    """ORM field that stores an ISO 3166-1 alpha-2 country code.

    The stored value is always a 2-character uppercase string.  Validation
    enforces membership in the ISO registry (plus any ``extra_countries``
    supplied at construction time).

    Args:
        extra_countries: Additional ``(code, name, dial_code)`` triples to
            recognise alongside the built-in ISO dataset.
        strict: When ``True`` (default) only 2-letter alphabetic codes pass
            validation.  Set to ``False`` to accept custom codes of other
            lengths.
        **kwargs: Forwarded to :class:`~openviper.db.fields.CharField`.

    Example::

        from openviper.contrib.countries import CountryField

        class UserProfile(Model):
            country = CountryField(null=True, db_index=True)
    """

    def __init__(
        self,
        extra_countries: _EXTRA_COUNTRIES_TYPE = (),
        strict: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("max_length", 2)
        super().__init__(**kwargs)
        self._column_type = f"CHAR({self.max_length})"
        self.extra_countries: _EXTRA_COUNTRIES_TYPE = extra_countries
        self.strict: bool = strict
        self._valid_codes: frozenset[str] = self._build_valid_codes()

    def _build_valid_codes(self) -> frozenset[str]:
        """Build the complete set of accepted codes as a frozenset."""
        if not self.extra_countries:
            return COUNTRY_CODES
        extra_codes = frozenset(c[0].upper() for c in self.extra_countries)
        return COUNTRY_CODES | extra_codes

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        """Return a :class:`Country` wrapper when accessed on a model instance."""
        if obj is None:
            # Class-level access returns the field descriptor itself.
            return self
        raw = obj.__dict__.get(self.name)
        if raw is None:
            return None
        if isinstance(raw, Country):
            return raw
        return Country(str(raw), self.extra_countries)

    def __set__(self, obj: Any, value: Any) -> None:
        """Store the normalised uppercase code in the instance dictionary."""
        if value is None:
            obj.__dict__[self.name] = None
        else:
            obj.__dict__[self.name] = str(value).upper()

    def to_python(self, value: Any) -> Country | None:
        """Normalise *value* to a :class:`Country` instance or return ``None``."""
        if value is None:
            return None
        if isinstance(value, Country) and value._extra == self.extra_countries:
            return value
        return Country(str(value), self.extra_countries)

    def to_db(self, value: Any) -> str | None:
        """Persist the normalised uppercase code."""
        if value is None:
            return None
        return str(value).upper()

    def validate(self, value: Any) -> None:
        """Validate that *value* is a known ISO country code.

        Raises:
            ValueError: For ``None`` on a non-nullable field, for a string
                that exceeds the safe two-character limit, or for an
                unrecognised code.
        """
        if value is not None and len(str(value)) > 10:
            raise ValueError("Country code exceeds maximum safe length.")

        super().validate(value)
        if value is None:
            return
        normalised = str(value).upper()
        if not validate_country(normalised, extra=self.extra_countries, strict=self.strict):
            raise ValueError(f"'{normalised}' is not a valid ISO 3166-1 alpha-2 country code.")

    def get_choices(self) -> tuple[tuple[str, str], ...]:
        """Return ``(code, name)`` pairs sorted alphabetically by name."""
        return get_country_choices(self.extra_countries)

    def get_country_name(self, code: str | None) -> str | None:
        """Return the English country name for *code*, or ``None``."""
        if code is None:
            return None
        from openviper.contrib.countries.utils import get_country_name

        return get_country_name(code, extra=self.extra_countries)

    def search(self, query: str) -> list[dict[str, str]]:
        """Search countries by partial name or exact code match.

        Returns a list of ``{"code": ..., "name": ..., "dial_code": ...}`` dicts.
        """
        from openviper.contrib.countries.utils import search_country

        return search_country(query, extra=self.extra_countries)

    def to_representation(self, value: str | None, *, full: bool = False) -> Any:
        """Serializer-friendly representation.

        Args:
            value: The stored ISO code.
            full: When ``True`` return a dict with ``code``, ``name``, and
                ``dial_code``.  When ``False`` (default) return the raw code.

        Returns:
            ISO code string or a ``dict`` when *full* is ``True``.
        """
        if value is None:
            return None
        normalised = str(value).upper()
        if not full:
            return normalised
        from openviper.contrib.countries.cache import get_countries, get_country

        info = get_country(normalised)
        if info is None and self.extra_countries:
            info = get_countries(self.extra_countries).get(normalised)
        if info is None:
            return {"code": normalised, "name": normalised, "dial_code": ""}
        return {"code": normalised, "name": info["name"], "dial_code": info["dial_code"]}

    @classmethod
    def openapi_schema(cls, extra_countries: _EXTRA_COUNTRIES_TYPE = ()) -> dict[str, Any]:
        """Return an OpenAPI 3.1 JSON-Schema snippet for this field type.

        Includes an ``enum`` of all valid country codes for client-side
        validation and IDE auto-complete support.

        Args:
            extra_countries: Additional codes to include in the enum.

        Returns:
            OpenAPI schema dict.
        """
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
