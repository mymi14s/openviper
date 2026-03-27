"""Built-in HTTP views for OpenViper.

Authentication views (login, logout, me) and pre-built route lists live here.
They are also re-exported from ``openviper.auth`` for convenience.
"""

from __future__ import annotations

from openviper.auth.views.base_login import BaseLoginView
from openviper.auth.views.jwt_login import JWTLoginView
from openviper.auth.views.logout import LogoutView
from openviper.auth.views.me import MeView
from openviper.auth.views.oauth2 import (
    BaseOAuth2CallbackView,
    BaseOAuth2InitView,
    GoogleOAuthCallbackView,
    GoogleOAuthInitView,
    google_oauth_routes,
)
from openviper.auth.views.routes import all_auth_routes, jwt_routes, session_routes, token_routes
from openviper.auth.views.session_login import SessionLoginView
from openviper.auth.views.token_login import TokenLoginView

__all__ = [
    "BaseLoginView",
    "JWTLoginView",
    "TokenLoginView",
    "SessionLoginView",
    "LogoutView",
    "MeView",
    "jwt_routes",
    "token_routes",
    "session_routes",
    "all_auth_routes",
    # OAuth2 views
    "BaseOAuth2InitView",
    "BaseOAuth2CallbackView",
    "GoogleOAuthInitView",
    "GoogleOAuthCallbackView",
    "google_oauth_routes",
]
