"""Example: Serializers for the UserProfile model with CountryField.

Demonstrates ModelSerializer with CountryField representation.
"""

from __future__ import annotations

from openviper.contrib.fields.countries import CountryField
from openviper.serializers import ModelSerializer

from .models import UserProfile

country_field = CountryField(null=True)


class ProfileSerializer(ModelSerializer):
    """Base serializer for UserProfile with country field representation."""

    class Meta:
        model = UserProfile
        fields = ["id", "name", "email", "country"]

    def serialize_country(self, instance: UserProfile, full: bool) -> dict:
        data = super().serialize(instance)
        data["country"] = country_field.to_representation(instance.country, full=full)
        return data


class ProfileCodeSerializer(ProfileSerializer):
    """Serialize a UserProfile, returning country as a plain ISO code."""

    def serialize(self, instance: UserProfile) -> dict:
        return self.serialize_country(instance, full=False)


class ProfileFullSerializer(ProfileSerializer):
    """Serialize a UserProfile, returning country as a full dict object."""

    def serialize(self, instance: UserProfile) -> dict:
        return self.serialize_country(instance, full=True)
