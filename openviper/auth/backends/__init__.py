"""Authentication backends for OpenViper."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import inspect
import logging
import os
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast

from openviper.auth.hashers import ARGON2_DUMMY_HASH, check_password
from openviper.auth.hooks import auth_hooks, build_auth_hook_context
from openviper.auth.models import AnonymousUser
from openviper.auth.request_state import set_auth_state
from openviper.auth.session.store import Session, get_session_store
from openviper.auth.session.utils import get_session_cookie_config
from openviper.auth.sessions import delete_session
from openviper.auth.user import get_user_by_id
from openviper.auth.utils import get_user_model
from openviper.conf import settings
from openviper.db.models import Q

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable


class AuthRequest(Protocol):
    """Request surface used by auth backend helpers."""

    cookies: Mapping[str, str]
    headers: Mapping[str, str]
    client: object
    user: object
    _session: object


class AuthResponse(Protocol):
    """Response surface used by session cookie helpers."""

    def set_cookie(
        self,
        *,
        key: str,
        value: str,
        max_age: int,
        expires: int,
        httponly: bool,
        secure: bool,
        samesite: str,
        path: str,
        domain: str | None,
    ) -> None: ...

    def delete_cookie(self, key: str, domain: str | None = None) -> None: ...


logger = logging.getLogger("openviper.auth.backends")

__all__ = [
    "get_user_by_id",
    "authenticate",
    "login",
    "logout",
]


class UserFilterResult(Protocol):
    """Structural interface for retrieving one filtered user."""

    async def first(self) -> Authenticable | None: ...


class UserLookupManager(Protocol):
    """Structural query interface required by password authentication."""

    def filter(self, *conditions: object, **filters: object) -> UserFilterResult: ...


def is_production_env() -> bool:
    """Check if running in production environment."""
    env = os.environ.get("ENVIRONMENT", "").lower()
    return env in ("production", "prod")


async def authenticate(
    username: str,
    password: str,
    request: object | None = None,
) -> Authenticable | None:
    """Authenticate a user by username/email + password.

    Args:
        username: Username or email address.
        password: Plaintext password.
        request: Optional Request object for audit logging (IP address).

    Returns:
        Authenticated User instance or None if authentication fails.

    Raises:
        AuthenticationFailed: Credentials are invalid.
    """
    user_model = get_user_model()
    client_ip = get_client_ip(cast("AuthRequest", request)) if request else "unknown"
    objects = cast("UserLookupManager", user_model.objects)

    user = await objects.filter(
        Q(username=username) | Q(email=username),
        is_active=True,
        ignore_permissions=True,
    ).first()

    if user is None:
        # Verify against a dummy hash so the response time is
        # indistinguishable from a real password check, preventing user
        # enumeration via timing side-channel.
        await check_password(password, ARGON2_DUMMY_HASH)
        logger.warning(
            "Authentication failed: user not found",
            extra={"username": username, "client_ip": client_ip, "reason": "user_not_found"},
        )
        return None

    if not await user.check_password(password):
        logger.warning(
            "Authentication failed: invalid password",
            extra={
                "username": username,
                "user_id": user.pk,
                "client_ip": client_ip,
                "reason": "invalid_password",
            },
        )
        return None

    # Fire-and-forget last_login update to keep response latency low.
    update_coro = update_last_login(user)
    task = asyncio.create_task(update_coro)
    if not isinstance(task, asyncio.Task) and inspect.iscoroutine(update_coro):
        update_coro.close()
    return user


async def update_last_login(user: Authenticable) -> None:
    """Update user's last_login timestamp in background."""
    try:
        user.last_login = datetime.datetime.now(datetime.UTC)
        await user.save(ignore_permissions=True)
    except (AttributeError, RuntimeError) as exc:
        logger.debug("Failed to update last_login for user %s: %s", getattr(user, "pk", "?"), exc)


def get_client_ip(request: AuthRequest) -> str:
    """Extract client IP address from request.

    Only trusts ``X-Forwarded-For`` / ``X-Real-IP`` when the direct TCP
    connection originates from a configured trusted proxy
    (``settings.TRUSTED_PROXIES``).  When multiple proxies are in the chain,
    the rightmost entry in ``X-Forwarded-For`` that precedes a trusted proxy
    is used, preventing IP spoofing via client-injected header values.
    """
    if not request:
        return "unknown"

    direct_ip = "unknown"
    if hasattr(request, "client") and request.client:
        direct_ip = getattr(request.client, "host", "unknown")

    trusted_proxies: frozenset[str] = frozenset(getattr(settings, "TRUSTED_PROXIES", ()))
    if trusted_proxies and direct_ip in trusted_proxies and hasattr(request, "headers"):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Walk right-to-left to find the first non-trusted IP,
            # matching the X-Forwarded-For security convention.
            ips = [ip.strip() for ip in forwarded.split(",")]
            for ip in reversed(ips):
                if ip not in trusted_proxies:
                    return str(ip)
            # Avoid trusting a chain made entirely of configured proxies.
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return str(real_ip.strip())

    return direct_ip


async def login(request: object, user: Authenticable, response: object | None = None) -> str:
    """Create a session for the given user and optionally set the session cookie.

    When *response* is provided the ``Set-Cookie`` header is written
    automatically, so callers do not need to call ``response.set_cookie``
    themselves.

    Args:
        request: The current Request object.
        user: Authenticated User instance.
        response: Optional Response object. When supplied the session cookie
            is set on the response automatically.

    Returns:
        The new session key.

    Example::

        user = await authenticate(username=username, password=password)
        response = RedirectResponse("/dashboard", status_code=302)
        await login(request, user, response)
        return response
    """

    store = get_session_store()
    auth_request = cast("AuthRequest", request)
    auth_response = cast("AuthResponse", response)
    user_id = user.pk
    if user_id is None:
        raise ValueError("Authenticated users must have a primary key.")
    data = {"user_id": str(user_id)}
    context = build_auth_hook_context(
        user=user,
        request=auth_request,
        auth_backend="session",
    )
    await auth_hooks.run_before_login(context)

    # Rotate existing sessions to prevent fixation.
    existing_session = getattr(auth_request, "_session", None)
    existing_key = existing_session.key if existing_session and existing_session.key else None
    if not existing_key:
        _cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        existing_key = auth_request.cookies.get(_cookie_name)

    if existing_key:
        new_session = await store.rotate(existing_key, user_id=user_id, data=data)
    else:
        new_session = await store.create(user_id=user_id, data=data)

    session_key: str = new_session.key
    auth_request.user = user
    auth_request._session = new_session
    scope = getattr(auth_request, "_scope", None)
    if isinstance(scope, dict):
        scope["session"] = new_session
    context.session = new_session

    if response is not None:
        config = get_session_cookie_config()
        expires_timestamp = int(time.time()) + config.max_age

        auth_response.set_cookie(
            key=config.cookie_name,
            value=session_key,
            max_age=config.max_age,
            expires=expires_timestamp,
            httponly=config.httponly,
            secure=config.secure,
            samesite=config.samesite,
            path=config.path,
            domain=config.domain,
        )

    await auth_hooks.run_on_login(context)
    return session_key


async def logout(request: object, response: object | None = None) -> None:
    """Invalidate the current user's session.

    When *response* is provided the session cookie is deleted automatically.

    Args:
        request: The current Request object.
        response: Optional Response object. When supplied the session cookie
            is cleared on the response automatically.
    """
    cookie_name = get_session_cookie_config().cookie_name

    auth_request = cast("AuthRequest", request)
    auth_response = cast("AuthResponse", response)
    session_key = auth_request.cookies.get(cookie_name)
    context = build_auth_hook_context(
        user=getattr(request, "user", None),
        request=auth_request,
        session=getattr(auth_request, "session", getattr(auth_request, "_session", None)),
        auth_backend="session",
    )

    if session_key:
        await delete_session(session_key)

    if response is not None:
        cookie_domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
        auth_response.delete_cookie(cookie_name, domain=cookie_domain)

    empty = Session(key="")
    auth_request.user = AnonymousUser()
    auth_request._session = empty
    scope = getattr(auth_request, "_scope", None)
    if isinstance(scope, dict):
        scope["session"] = empty
    await auth_hooks.run_on_logout(context)
    set_auth_state(auth_request, "logout_hook_ran", True)
