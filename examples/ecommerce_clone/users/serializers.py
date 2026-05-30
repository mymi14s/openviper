"""User serializers."""

from __future__ import annotations

from openviper.serializers import Serializer


class UserRegistrationSerializer(Serializer):
    """Serializer for user registration."""

    username: str
    email: str
    password: str
    name: str | None = None
    address: str | None = None


class UserLoginSerializer(Serializer):
    """Serializer for user login."""

    username: str
    password: str


class UserResponseSerializer(Serializer):
    """Serializer for user response."""

    id: int
    username: str
    email: str
    name: str | None = None
    address: str | None = None
    is_active: bool
    created_at: str | None = None
