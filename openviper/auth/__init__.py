"""OpenViper authentication package."""

from openviper.auth.backends import authenticate, get_user_by_id, login, logout
from openviper.auth.decorators import (
    login_required,
    permission_required,
    role_required,
    staff_required,
    superuser_required,
)
from openviper.auth.hashers import check_password, make_password
from openviper.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_token_unverified,
)
from openviper.auth.models import (
    AnonymousUser,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from openviper.auth.utils import get_user_model

__all__ = [
    "User",
    "AnonymousUser",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
    "make_password",
    "check_password",
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_token_unverified",
    "authenticate",
    "login",
    "logout",
    "get_user_by_id",
    "get_user_model",
    "login_required",
    "permission_required",
    "role_required",
    "superuser_required",
    "staff_required",
]
