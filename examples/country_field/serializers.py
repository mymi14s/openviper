"""Example: Serializers for the UserProfile model with CountryField.

Two serializer variants are shown:
  - ProfileCodeSerializer  — returns country as a plain ISO code string.
  - ProfileFullSerializer  — returns country as a full dict object.
"""

from __future__ import annotations

from typing import Any

from openviper.contrib.countries import CountryField


class ProfileCodeSerializer:
    """Serialize a UserProfile, returning country as a plain ISO code.

    Output example::

        {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com",
            "country": "GB"
        }
    """

    def serialize(self, instance: Any) -> dict[str, Any]:
        field = CountryField(null=True)
        return {
            "id": getattr(instance, "id", None),
            "name": instance.name,
            "email": instance.email,
            "country": field.to_representation(instance.country, full=False),
        }


class ProfileFullSerializer:
    """Serialize a UserProfile, returning country as a full object.

    Output example::

        {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com",
            "country": {
                "code": "GB",
                "name": "United Kingdom",
                "dial_code": "+44"
            }
        }
    """

    def serialize(self, instance: Any) -> dict[str, Any]:
        field = CountryField(null=True)
        return {
            "id": getattr(instance, "id", None),
            "name": instance.name,
            "email": instance.email,
            "country": field.to_representation(instance.country, full=True),
        }
