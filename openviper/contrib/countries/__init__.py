"""openviper.contrib.countries — ISO 3166-1 alpha-2 CountryField.

Optional contrib package that provides a lightweight, zero-overhead
country code field for OpenViper models.  No database tables are used;
all lookups operate on an in-memory frozenset of ISO codes.

Public API
----------
CountryField
    ORM field for storing ISO 3166-1 alpha-2 country codes.

Utility helpers (re-exported for convenience)
---------------------------------------------
validate_country(code) -> bool
get_country_name(code) -> str | None
get_dial_code(code) -> str | None
search_country(query) -> list[dict]
get_country_choices() -> tuple[tuple[str, str], ...]

Example::

    from openviper.db import Model
    from openviper.contrib.countries import CountryField

    class UserProfile(Model):
        country = CountryField(null=True, db_index=True)
"""

from openviper.contrib.countries.cache import get_country_choices
from openviper.contrib.countries.country import Country
from openviper.contrib.countries.field import CountryField
from openviper.contrib.countries.utils import (
    get_country_name,
    get_dial_code,
    search_country,
    validate_country,
)

__all__ = [
    "Country",
    "CountryField",
    "get_country_choices",
    "get_country_name",
    "get_dial_code",
    "search_country",
    "validate_country",
]
