"""Session lifecycle manager for OpenViper.

Provides high-level login and logout workflows, including session
rotation on login to prevent session-fixation attacks.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Protocol, cast

from openviper.auth.hooks import AuthHookContext, auth_hooks, build_auth_hook_context
from openviper.auth.models import AnonymousUser
from openviper.auth.request_state import get_auth_state, set_auth_state
from openviper.auth.session.store import BaseSessionStore, Session, get_session_store
from openviper.conf import settings

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable
    from openviper.http.request import Request
    from openviper.http.types import UserProtocol


class CookieDeletingResponse(Protocol):
    """Response surface required for session cookie deletion."""

    def delete_cookie(self, key: str, domain: str | None = None) -> None: ...


logger = logging.getLogger("openviper.auth.session")


class SessionManager:
    """High-level session lifecycle management.

    Handles the login/logout workflows: creating sessions on login
    (with rotation if a session already exists) and deleting them on logout.

    Args:
        store: A session store instance. Defaults to the configured store.
    """

    def __init__(self, store: BaseSessionStore | None = None) -> None:
        self.store: BaseSessionStore = store or get_session_store()

    async def login(self, request: Request, user: Authenticable) -> str:
        """Create (or rotate) a session for the authenticated user.

        If the request already carries a valid session cookie, the old session
        is invalidated before a new one is created (session-fixation protection).

        Args:
            request: The current request object.
            user: The authenticated user instance.

        Returns:
            The new session key.  The caller is responsible for setting
            the ``Set-Cookie`` header on the response.
        """
        context = self.login_hook_context(request, user)
        if get_auth_state(request, "before_login_hook_ran", False) is not True:
            await auth_hooks.run_before_login(context)
            set_auth_state(request, "before_login_hook_ran", True)

        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        existing_session = getattr(request, "session", None)
        existing_key = existing_session.key if existing_session else None

        if not existing_key:
            with contextlib.suppress(AttributeError, TypeError):
                existing_key = request.cookies.get(cookie_name)

        user_id = user.pk
        if user_id is None:
            raise ValueError("Authenticated users must have a primary key.")
        data = {"user_id": str(user_id)}

        if existing_key:
            session = await self.store.rotate(
                existing_key,
                user_id=user_id,
                data=data,
            )
            # Handle both old (str) and new (Session) rotate return types.
            if isinstance(session, str):
                session_key = session
                session = await self.store.load(session_key)
            else:
                session_key = session.key
        else:
            session = await self.store.create(user_id=user_id, data=data)
            session_key = session.key

        request.user = cast("UserProtocol | None", user)
        request._session = session
        # Propagate session into ASGI scope so send_wrapper reads the updated data.
        scope = getattr(request, "_scope", None)
        if isinstance(scope, dict):
            scope["session"] = session
        context.session = session
        await auth_hooks.run_on_login(context)
        set_auth_state(request, "login_hook_ran", True)
        return session_key

    async def logout(self, request: Request, response: object | None = None) -> None:
        """Invalidate the current user's session.

        Deletes the session from the store and resets ``request.user`` to
        AnonymousUser.

        Args:
            request: The current request object.
        """
        session = getattr(request, "session", None)
        context = self.logout_hook_context(request, session)
        if session and session.key:
            await self.store.delete(session.key)

        empty = Session(key="", store=self.store)
        request.user = AnonymousUser()
        request._session = empty
        scope = getattr(request, "_scope", None)
        if isinstance(scope, dict):
            scope["session"] = empty
        if response is not None:
            cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
            cookie_domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
            cast("CookieDeletingResponse", response).delete_cookie(
                cookie_name, domain=cookie_domain
            )
        await auth_hooks.run_on_logout(context)
        set_auth_state(request, "logout_hook_ran", True)

    def login_hook_context(self, request: Request, user: Authenticable) -> AuthHookContext:
        """Return the current login hook context or create one for sessions."""
        context = get_auth_state(request, "hook_context")
        if isinstance(context, AuthHookContext):
            context.user = user
            context.auth_backend = "session"
            return context
        context = build_auth_hook_context(
            user=user,
            request=request,
            auth_backend="session",
        )
        set_auth_state(request, "hook_context", context)
        return context

    def logout_hook_context(self, request: Request, session: object | None) -> AuthHookContext:
        """Return the current logout hook context or create one for sessions."""
        context = get_auth_state(request, "logout_hook_context")
        if isinstance(context, AuthHookContext):
            context.session = session
            return context
        return build_auth_hook_context(
            user=getattr(request, "user", None),
            request=request,
            session=session,
            auth_backend="session",
        )
