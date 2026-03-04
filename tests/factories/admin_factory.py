from __future__ import annotations

from typing import Any

from openviper.admin.registry import admin
from openviper.auth import get_user_model
from openviper.auth.models import Permission, Role
from openviper.db.models import Model


async def create_user(
    username: str,
    email: str = None,
    is_staff: bool = False,
    is_superuser: bool = False,
    password: str = "password123",
):
    User = get_user_model()
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        is_staff=is_staff,
        is_superuser=is_superuser,
        is_active=True,
    )
    user.set_password(password)
    await user.save()
    return user


async def create_admin_user(username: str = "admin"):
    return await create_user(username, is_staff=True, is_superuser=True)


async def create_staff_user(username: str = "staff"):
    return await create_user(username, is_staff=True, is_superuser=False)


async def create_regular_user(username: str = "user"):
    return await create_user(username, is_staff=False, is_superuser=False)
