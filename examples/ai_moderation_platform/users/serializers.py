"""User and authentication serializers."""

from __future__ import annotations

from openviper.serializers import Serializer


class UserRegistrationSerializer(Serializer):
    """Serializer for user registration."""

    username: str
    email: str
    password: str
    first_name: str | None = None
    last_name: str | None = None


class UserLoginSerializer(Serializer):
    """Serializer for user login."""

    username: str
    password: str


class UserResponseSerializer(Serializer):
    """Serializer for user response."""

    id: int
    username: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    created_at: str


class TokenResponseSerializer(Serializer):
    """Serializer for JWT token response."""

    access_token: str
    token_type: str
    user: UserResponseSerializer
