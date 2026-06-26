"""ISO 3166-1 alpha-2 CountryField and utility helpers.

Re-exports CountryField, Country, validate_country, get_country_name,
get_dial_code, search_country, and get_country_choices.
"""

from openviper.contrib.fields.countries.cache import get_country_choices
from openviper.contrib.fields.countries.country import Country
from openviper.contrib.fields.countries.field import CountryField
from openviper.contrib.fields.countries.serializer import serialize_value as _serialize_country
from openviper.contrib.fields.countries.utils import (
    get_country_name,
    get_dial_code,
    search_country,
    validate_country,
)
from openviper.serializers.base import register_contrib_serializer

register_contrib_serializer("Country", _serialize_country)

__all__ = [
    "Country",
    "CountryField",
    "get_country_choices",
    "get_country_name",
    "get_dial_code",
    "search_country",
    "validate_country",
]
