"""User model for Ecommerce Clone."""

from __future__ import annotations

from openviper.auth.models import AbstractUser as BaseUser
from openviper.db import fields


class User(BaseUser):
    """Extended user model for the ecommerce platform.

    Inherits from OpenViper's abstract User model which includes:
    - username, email, password
    - is_active, is_superuser, is_staff
    - Role and permission management
    """

    _app_name = "users"

    name = fields.CharField(max_length=255, null=True, blank=True)
    address = fields.TextField(null=True, blank=True)

    class Meta:
        table_name = "users_user"

    def __str__(self) -> str:
        return self.username or self.email or ""
