"""Shared base class for all built-in login views."""

from __future__ import annotations

from typing import Any

from openviper.auth.backends import authenticate
from openviper.exceptions import Unauthorized
from openviper.http.views import View


class BaseLoginView(View):
    """Abstract base for JWT, Token, and Session login views.

    Subclasses must implement :meth:`post`.  The :meth:`authenticate_user`
    helper centralises credential validation so each concrete view only
    handles the token or session creation step.
    """

    async def authenticate_user(self, request: Any) -> Any:
        """Validate credentials from the request body and return the user.

        Expects a JSON body with ``username`` and ``password`` keys.

        Args:
            request: The current request object.

        Returns:
            Authenticated user instance.

        Raises:
            Unauthorized: Credentials are missing, invalid, the account does
                not exist, or the account is inactive.
        """
        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:
            raise Unauthorized("Invalid request body.") from exc

        username: str = body.get("username", "")
        password: str = body.get("password", "")

        if not username or not password:
            raise Unauthorized("Username and password are required.")

        user = await authenticate(username=username, password=password, request=request)
        if user is None:
            raise Unauthorized("Invalid credentials.")

        if not getattr(user, "is_active", True):
            raise Unauthorized("Account is inactive.")

        return user
