"""Authentication backends for OpenViper."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import time
from typing import Any

from openviper.auth.hashers import _ARGON2_DUMMY_HASH, check_password
from openviper.auth.models import AnonymousUser
from openviper.auth.sessions import create_session, delete_session
from openviper.auth.user import get_user_by_id
from openviper.auth.utils import get_user_model
from openviper.conf import settings
from openviper.db.models import Q

logger = logging.getLogger("openviper.auth.backends")

__all__ = [
    "get_user_by_id",
    "authenticate",
    "login",
    "logout",
]


def _is_production_env() -> bool:
    """Check if running in production environment."""
    env = os.environ.get("ENVIRONMENT", "").lower()
    return env in ("production", "prod")


async def authenticate(username: str, password: str, request: Any = None) -> Any:
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
    User = get_user_model()  # noqa: N806
    client_ip = _get_client_ip(request) if request else "unknown"

    # Single query with OR condition for username or email
    user = await User.objects.filter(  # type: ignore[attr-defined]
        Q(username=username) | Q(email=username),
        is_active=True,
        ignore_permissions=True,
    ).first()

    if user is None:
        # Perform a real Argon2 verify against a precomputed dummy hash so the
        # response time is indistinguishable from a failed password check for a
        # real account, preventing user-enumeration via timing side-channel.
        await check_password(password, _ARGON2_DUMMY_HASH)
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

    # Successful authentication
    logger.info(
        "Authentication successful",
        extra={"username": username, "user_id": user.pk, "client_ip": client_ip},
    )

    # Update last_login in background to avoid blocking the response
    asyncio.create_task(_update_last_login(user))
    return user


async def _update_last_login(user: Any) -> None:
    """Update user's last_login timestamp in background."""
    try:
        user.last_login = datetime.datetime.now(datetime.UTC)
        await user.save(ignore_permissions=True)
    except Exception as exc:
        # last_login is not critical; log but do not propagate
        logger.debug("Failed to update last_login for user %s: %s", getattr(user, "pk", "?"), exc)


def _get_client_ip(request: Any) -> str:
    """Extract client IP address from request.

    Checks X-Forwarded-For, X-Real-IP headers and falls back to direct connection IP.
    """
    if not request:
        return "unknown"

    # Check for proxy headers (be cautious with these in production)
    if hasattr(request, "headers"):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For can contain multiple IPs, use the first one
            return str(forwarded.split(",")[0].strip())

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return str(real_ip.strip())

    # Fall back to direct connection IP
    if hasattr(request, "client") and request.client:
        return getattr(request.client, "host", "unknown")

    return "unknown"


async def login(request: Any, user: Any, response: Any = None) -> str:
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

    session_key = await create_session(user_id=user.pk, data={"user_id": user.pk})
    request.user = user

    # Audit log for session creation
    client_ip = _get_client_ip(request)
    logger.info(
        "User session created",
        extra={
            "user_id": user.pk,
            "username": getattr(user, "username", "unknown"),
            "client_ip": client_ip,
            "session_key": session_key[:16] + "..." if len(session_key) > 16 else session_key,
        },
    )

    if response is not None:
        cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        cookie_domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
        session_timeout = getattr(settings, "SESSION_TIMEOUT", datetime.timedelta(hours=1))
        max_age_seconds = int(session_timeout.total_seconds())

        # Calculate expires timestamp (needed for older browsers)
        expires_timestamp = int(time.time()) + max_age_seconds

        response.set_cookie(
            key=cookie_name,
            value=session_key,
            max_age=max_age_seconds,
            expires=expires_timestamp,
            httponly=getattr(settings, "SESSION_COOKIE_HTTPONLY", True),
            secure=getattr(settings, "SESSION_COOKIE_SECURE", _is_production_env()),
            samesite=getattr(settings, "SESSION_COOKIE_SAMESITE", "lax"),
            path=getattr(settings, "SESSION_COOKIE_PATH", "/"),
            domain=cookie_domain,
        )

    return session_key


async def logout(request: Any, response: Any = None) -> None:
    """Invalidate the current user's session.

    When *response* is provided the session cookie is deleted automatically.

    Args:
        request: The current Request object.
        response: Optional Response object. When supplied the session cookie
            is cleared on the response automatically.
    """
    cookie_name = "sessionid"
    with contextlib.suppress(Exception):
        cookie_name = settings.SESSION_COOKIE_NAME

    session_key = request.cookies.get(cookie_name)

    # Get user info for audit log before invalidating
    user = getattr(request, "user", None)
    user_id = getattr(user, "pk", None) if user and not isinstance(user, AnonymousUser) else None
    username = getattr(user, "username", "anonymous") if user else "anonymous"
    client_ip = _get_client_ip(request)

    if session_key:
        await delete_session(session_key)

        # Audit log
        logger.info(
            "User logged out",
            extra={
                "user_id": user_id,
                "username": username,
                "client_ip": client_ip,
                "session_key": session_key[:16] + "..." if len(session_key) > 16 else session_key,
            },
        )

    if response is not None:
        response.delete_cookie(cookie_name)

    request.user = AnonymousUser()
