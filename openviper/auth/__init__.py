"""OpenViper authentication package."""

from openviper.auth.authentications import (
    TokenAuthentication,
    clear_token_auth_cache,
    create_token,
)
from openviper.auth.authentications import (
    revoke_token as revoke_auth_token,
)
from openviper.auth.backends import authenticate, get_user_by_id, login, logout
from openviper.auth.backends.jwt_backend import JWTBackend
from openviper.auth.backends.session_backend import SessionBackend
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
from openviper.auth.manager import AuthManager
from openviper.auth.models import (
    AnonymousUser,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from openviper.auth.session import DatabaseSessionStore, SessionManager, SessionMiddleware
from openviper.auth.sessions import clear_session_cache
from openviper.auth.token_blocklist import clear_token_cache
from openviper.auth.utils import get_user_model
from openviper.auth.views.base_login import BaseLoginView
from openviper.auth.views.jwt_login import JWTLoginView
from openviper.auth.views.logout import LogoutView
from openviper.auth.views.me import MeView
from openviper.auth.views.routes import all_auth_routes, jwt_routes, session_routes, token_routes
from openviper.auth.views.session_login import SessionLoginView
from openviper.auth.views.token_login import TokenLoginView

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
    "clear_session_cache",
    "clear_token_cache",
    # Token authentication
    "TokenAuthentication",
    "create_token",
    "revoke_auth_token",
    "clear_token_auth_cache",
    # New session system
    "AuthManager",
    "JWTBackend",
    "SessionBackend",
    "DatabaseSessionStore",
    "SessionManager",
    "SessionMiddleware",
    # Auth views
    "BaseLoginView",
    "JWTLoginView",
    "TokenLoginView",
    "SessionLoginView",
    "LogoutView",
    "MeView",
    # Auth route lists
    "jwt_routes",
    "token_routes",
    "session_routes",
    "all_auth_routes",
]
