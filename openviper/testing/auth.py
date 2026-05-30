"""Authentication helpers for OpenViper tests."""

import typing as t
from collections.abc import Iterable

from openviper.auth.jwt import create_access_token

if t.TYPE_CHECKING:
    import httpx


def token_for_user(user: object, extra_claims: dict[str, object] | None = None) -> str:
    """Create a JWT access token for a user-like object."""

    user_id = getattr(user, "pk", None) or getattr(user, "id", None)
    if user_id is None:
        raise RuntimeError("token_for_user() requires a user with pk or id.")
    return create_access_token(user_id=str(user_id), extra_claims=extra_claims)


def force_authenticate(client: httpx.AsyncClient, user: object) -> httpx.AsyncClient:
    """Attach a bearer token to an existing async test client."""

    client.headers["Authorization"] = f"Bearer {token_for_user(user)}"
    return client


async def login_user(client: httpx.AsyncClient, path: str, **credentials: object) -> httpx.Response:
    """Post credentials to a login route using the test client."""

    return await client.post(path, json=credentials)


def attach_bearer_token(client: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def attach_session_cookie(
    client: httpx.AsyncClient,
    value: str,
    cookie_name: str = "sessionid",
) -> httpx.AsyncClient:
    client.cookies.set(cookie_name, value)
    return client


def with_permissions(user: object, permissions: Iterable[str]) -> object:
    """Attach a permission set to a user object in-place."""
    object.__setattr__(user, "permissions", set(permissions))
    return user


def with_roles(user: object, roles: Iterable[str]) -> object:
    """Attach a role set to a user object in-place."""
    object.__setattr__(user, "roles", set(roles))
    return user
