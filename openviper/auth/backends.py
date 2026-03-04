"""Authentication backends for OpenViper."""

from __future__ import annotations

import contextlib
import datetime
from typing import Any

from openviper.auth.hashers import check_password
from openviper.auth.models import AnonymousUser
from openviper.auth.utils import get_user_model
from openviper.conf import settings
from openviper.exceptions import AuthenticationFailed


async def get_user_by_id(user_id: int) -> Any | None:
    """Load a user by primary key.

    Returns:
        User instance or None if not found.
    """
    try:
        User = get_user_model()
        return await User.objects.get_or_none(id=user_id, ignore_permissions=True)
    except Exception:
        return None


async def authenticate(username: str, password: str) -> Any:
    """Authenticate a user by username/email + password.

    Args:
        username: Username or email address.
        password: Plaintext password.

    Returns:
        Authenticated User instance.

    Raises:
        AuthenticationFailed: Credentials are invalid.
    """
    User = get_user_model()
    # Try username first, then email
    user = await User.objects.get_or_none(
        username=username, is_active=True, ignore_permissions=True
    )
    if user is None:
        user = await User.objects.get_or_none(
            email=username, is_active=True, ignore_permissions=True
        )
    if user is None:
        # Perform a dummy hash check to prevent timing attacks
        check_password(password, "argon2$dummy")
        raise AuthenticationFailed()
    if not user.check_password(password):
        raise AuthenticationFailed()

    # Update last_login
    user.last_login = datetime.datetime.now(datetime.timezone.utc)
    await user.save(ignore_permissions=True)

    return user


async def login(request: Any, user: Any) -> str:
    """Create and set a session for the given user.

    Args:
        request: The current Request object.
        user: Authenticated User instance.

    Returns:
        The new session key.
    """
    from openviper.auth.sessions import create_session

    session_key = await create_session(user_id=user.pk, data={"user_id": user.pk})
    request.user = user
    return session_key


async def logout(request: Any) -> None:
    """Invalidate the current user's session.

    Args:
        request: The current Request object.
    """
    cookie_name = "sessionid"
    with contextlib.suppress(Exception):
        cookie_name = settings.SESSION_COOKIE_NAME

    session_key = request.cookies.get(cookie_name)
    if session_key:
        from openviper.auth.sessions import delete_session

        await delete_session(session_key)

    request.user = AnonymousUser()
