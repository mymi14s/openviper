"""Shared base class for all built-in login views."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openviper.auth.backends import authenticate
from openviper.auth.exceptions import AuthHookExecutionError, AuthHookReject
from openviper.auth.hooks import AuthHookContext, auth_hooks, build_auth_hook_context
from openviper.auth.request_state import get_auth_state, set_auth_state
from openviper.auth.types import LoginCredentials
from openviper.exceptions import Unauthorized
from openviper.http.views import View

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable
    from openviper.http.request import Request


class BaseLoginView(View):
    """Abstract base for JWT, Token, and Session login views.

    Subclasses must implement :meth:`post`.  The :meth:`authenticate_user`
    helper centralises credential validation so each concrete view only
    handles the token or session creation step.
    """

    async def authenticate_user(self, request: Request) -> Authenticable:
        """Validate credentials from the request body and return the user.

        Uses :class:`LoginCredentials` to whitelist only the expected fields
        from the JSON body, preventing mass-assignment attacks.

        Args:
            request: The current request object.

        Returns:
            Authenticated user instance.

        Raises:
            Unauthorized: Credentials are missing, invalid, the account does
                not exist, or the account is inactive.
        """
        try:
            body: dict[str, object] = await request.json()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise Unauthorized("Invalid request body.") from exc

        try:
            creds = LoginCredentials.from_request_body(body)
        except ValueError as exc:
            raise Unauthorized(str(exc)) from exc

        user = await authenticate(username=creds.username, password=creds.password, request=request)
        if user is None:
            raise Unauthorized("Invalid credentials.")

        if not getattr(user, "is_active", True):
            raise Unauthorized("Account is inactive.")

        context = build_auth_hook_context(
            user=user,
            credentials=body,
            request=request,
            auth_backend="password",
        )
        try:
            await auth_hooks.run_before_login(context)
        except AuthHookReject as exc:
            raise Unauthorized(str(exc) or "Login rejected.") from exc
        except AuthHookExecutionError as exc:
            raise Unauthorized("Login rejected.") from exc

        set_auth_state(request, "hook_context", context)
        set_auth_state(request, "before_login_hook_ran", True)
        return user

    def auth_hook_context(
        self,
        request: Request,
        user: Authenticable,
        auth_backend: str,
    ) -> AuthHookContext:
        """Return the request hook context or a sanitized fallback context."""
        existing = get_auth_state(request, "hook_context")
        if isinstance(existing, AuthHookContext):
            existing.user = user
            if existing.auth_backend is None:
                existing.auth_backend = auth_backend
            return existing
        return build_auth_hook_context(user=user, request=request, auth_backend=auth_backend)

    async def run_on_login_hook(self, context: AuthHookContext) -> None:
        """Run post-login hooks and preserve the login response by default."""
        await auth_hooks.run_on_login(context)
