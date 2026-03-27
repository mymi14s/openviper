"""Pre-built route tuples for all built-in authentication views.

Import the route list that matches your authentication strategy and include
it in your application router:

.. code-block:: python

    from openviper.routing import Router
    from openviper.auth.views.routes import all_auth_routes

    router = Router(prefix="/auth")

    for path, handler, methods in all_auth_routes:
        router.add(path, handler, methods=methods)

Available route groups
----------------------

``jwt_routes``
    Login (returns access + refresh JWT) and logout.

``token_routes``
    Login (returns opaque token) and logout.

``session_routes``
    Login (sets session cookie) and logout.

``all_auth_routes``
    All of the above **plus** a shared ``/me`` route.  Use this when you
    want to support every authentication scheme simultaneously.

Route tuple format
------------------
Each entry is a 3-tuple ``(path: str, handler: Callable, methods: list[str])``.
"""

from __future__ import annotations

from openviper.auth.views.jwt_login import JWTLoginView
from openviper.auth.views.logout import LogoutView
from openviper.auth.views.me import MeView
from openviper.auth.views.session_login import SessionLoginView
from openviper.auth.views.token_login import TokenLoginView

# A route entry: (path, view handler, HTTP methods)
_RouteEntry = tuple[str, object, list[str]]


# Private named subclasses so each logout route gets a distinct handler name,
# avoiding "duplicate route name" warnings from the router.
class _JWTLogoutView(LogoutView):
    pass


class _TokenLogoutView(LogoutView):
    pass


class _SessionLogoutView(LogoutView):
    pass


jwt_routes: list[_RouteEntry] = [
    ("/jwt/login", JWTLoginView.as_view(), ["POST"]),
    ("/jwt/logout", _JWTLogoutView.as_view(), ["POST"]),
]
"""JWT login + logout routes."""

token_routes: list[_RouteEntry] = [
    ("/token/login", TokenLoginView.as_view(), ["POST"]),
    ("/token/logout", _TokenLogoutView.as_view(), ["POST"]),
]
"""Opaque-token login + logout routes."""

session_routes: list[_RouteEntry] = [
    ("/session/login", SessionLoginView.as_view(), ["POST"]),
    ("/session/logout", _SessionLogoutView.as_view(), ["POST"]),
]
"""Session-cookie login + logout routes."""

all_auth_routes: list[_RouteEntry] = [
    *jwt_routes,
    *token_routes,
    *session_routes,
    ("/me", MeView.as_view(), ["GET"]),
]
"""All authentication routes (JWT + Token + Session + Me)."""

__all__ = [
    "JWTLoginView",
    "TokenLoginView",
    "SessionLoginView",
    "LogoutView",
    "MeView",
    "jwt_routes",
    "token_routes",
    "session_routes",
    "all_auth_routes",
]
