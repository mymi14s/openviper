"""Example: Serializers for the UserProfile model with CountryField.

Demonstrates ModelSerializer with CountryField representation.
"""

from __future__ import annotations

from openviper.contrib.fields.countries import CountryField
from openviper.serializers import ModelSerializer

from .models import UserProfile


class ProfileCodeSerializer(ModelSerializer):
    """Serialize a UserProfile, returning country as a plain ISO code."""

    class Meta:
        model = UserProfile
        fields = ["id", "name", "email", "country"]

    def serialize(self, instance: UserProfile) -> dict:
        data = super().serialize(instance)
        field = CountryField(null=True)
        data["country"] = field.to_representation(instance.country, full=False)
        return data


class ProfileFullSerializer(ModelSerializer):
    """Serialize a UserProfile, returning country as a full dict object."""

    class Meta:
        model = UserProfile
        fields = ["id", "name", "email", "country"]

    def serialize(self, instance: UserProfile) -> dict:
        data = super().serialize(instance)
        field = CountryField(null=True)
        data["country"] = field.to_representation(instance.country, full=True)
        return data
