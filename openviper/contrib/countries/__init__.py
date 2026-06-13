"""ISO 3166-1 alpha-2 CountryField and utility helpers.

.. deprecated::
   Import from ``openviper.contrib.fields.countries`` instead.
   This module will be removed in a future release.
"""

from openviper.contrib.fields.countries import (
    Country,
    CountryField,
    get_country_choices,
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
