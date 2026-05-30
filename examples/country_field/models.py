"""Example: UserProfile model with CountryField.

This module demonstrates how to define a model that stores an ISO 3166-1
alpha-2 country code using CountryField.
"""

from __future__ import annotations

from openviper.contrib.countries import CountryField
from openviper.db import Model
from openviper.db.fields import CharField, DateTimeField, EmailField


class UserProfile(Model):
    """A user profile with a country field."""

    _app_name = "country_field_example"

    name = CharField(max_length=255)
    email = EmailField()
    country = CountryField(null=True, db_index=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "example_user_profiles"

    def __str__(self) -> str:
        return f"{self.name} ({self.country or 'no country'})"
