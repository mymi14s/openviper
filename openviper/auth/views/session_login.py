"""Session login view — creates a session cookie."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openviper.auth.session.manager import SessionManager
from openviper.auth.views.base_login import BaseLoginView
from openviper.conf import settings
from openviper.http.response import JSONResponse

if TYPE_CHECKING:
    from openviper.http.request import Request


class SessionLoginView(BaseLoginView):
    """Handle ``POST /auth/session/login``.

    Accepts ``{"username": "...", "password": "..."}`` and sets a
    ``Set-Cookie`` header on a successful response.

    Response body::

        {"detail": "Logged in."}
    """

    async def post(self, request: Request, **kwargs: Any) -> JSONResponse:
        """Authenticate credentials and establish a session cookie."""
        user = await self.authenticate_user(request)
        manager = SessionManager()
        session_key = await manager.login(request, user)

        cookie_name: str = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        httponly: bool = getattr(settings, "SESSION_COOKIE_HTTPONLY", True)
        samesite: str = getattr(settings, "SESSION_COOKIE_SAMESITE", "lax")
        secure: bool = getattr(settings, "SESSION_COOKIE_SECURE", False)

        response = JSONResponse({"detail": "Logged in."})
        response.set_cookie(
            cookie_name,
            session_key,
            httponly=httponly,
            samesite=samesite,
            secure=secure,
        )
        return response
