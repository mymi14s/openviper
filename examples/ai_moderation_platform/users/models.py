"""User models for AI Moderation Platform."""

from __future__ import annotations

from openviper.auth.models import User as BaseUser


class User(BaseUser):
    """Extended user model for the platform.

    Inherits from OpenViper's base User model which includes:
    - username, email, password
    - is_active, is_superuser, is_staff
    - Role and permission management
    """

    _app_name = "users"

    class Meta:
        table_name = "users_user"

    def __str__(self) -> str:
        return self.username or ""
