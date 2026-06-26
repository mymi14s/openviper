"""Session login view - creates a session cookie."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.auth.session.manager import SessionManager
from openviper.auth.session.utils import get_session_cookie_config
from openviper.auth.views.base_login import BaseLoginView
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

    async def post(self, request: Request, **kwargs: object) -> JSONResponse:
        """Authenticate credentials and establish a session cookie."""
        user = await self.authenticate_user(request)
        manager = SessionManager()
        session_key = await manager.login(request, user)

        config = get_session_cookie_config()

        response = JSONResponse({"detail": "Logged in."})
        response.set_cookie(
            config.cookie_name,
            session_key,
            max_age=config.max_age,
            path=config.path,
            domain=config.domain,
            httponly=config.httponly,
            samesite=config.samesite,
            secure=config.secure,
        )
        return response
