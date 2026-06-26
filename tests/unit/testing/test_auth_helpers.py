"""Tests for OpenViper authentication test helpers."""

from __future__ import annotations

import dataclasses

import httpx
import pytest

from openviper.testing.auth import (
    attach_bearer_token,
    attach_session_cookie,
    force_authenticate,
    token_for_user,
    with_permissions,
    with_roles,
)


@dataclasses.dataclass(slots=True)
class StubUser:
    """Minimal user-like object for testing auth helpers."""

    __test__ = False

    id: int
    pk: int
    email: str = "user@example.com"
    permissions: set[str] = dataclasses.field(default_factory=set)
    roles: set[str] = dataclasses.field(default_factory=set)


@dataclasses.dataclass(slots=True)
class IdlessUser:
    """User-like object with no id or pk attribute."""

    __test__ = False

    email: str = "noid@example.com"


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="http://testserver")


def test_token_for_user_returns_non_empty_jwt_string() -> None:
    user = StubUser(id=42, pk=42)

    token = token_for_user(user)

    assert isinstance(token, str)
    assert len(token) > 0
    # JWT tokens consist of three dot-separated base64url segments.
    assert token.count(".") == 2


def test_token_for_user_uses_pk_when_id_absent() -> None:
    user = StubUser(id=0, pk=99)
    # Force id to be falsy so pk is used.
    object.__setattr__(user, "id", None)

    token = token_for_user(user)

    assert isinstance(token, str)


def test_token_for_user_raises_when_no_id_or_pk() -> None:
    user = IdlessUser()

    with pytest.raises(RuntimeError, match="pk or id"):
        token_for_user(user)


def test_force_authenticate_sets_authorization_header() -> None:
    user = StubUser(id=1, pk=1)
    client = make_client()

    authenticated = force_authenticate(client, user)

    assert "Authorization" in authenticated.headers
    assert authenticated.headers["Authorization"].startswith("Bearer ")


def test_force_authenticate_returns_same_client_instance() -> None:
    user = StubUser(id=1, pk=1)
    client = make_client()

    result = force_authenticate(client, user)

    assert result is client


def test_attach_bearer_token_sets_authorization_header() -> None:
    client = make_client()

    result = attach_bearer_token(client, "mytoken")

    assert result.headers["Authorization"] == "Bearer mytoken"


def test_attach_session_cookie_sets_default_cookie_name() -> None:
    client = make_client()

    result = attach_session_cookie(client, "abc123")

    assert result.cookies.get("sessionid") == "abc123"


def test_attach_session_cookie_respects_custom_cookie_name() -> None:
    client = make_client()

    result = attach_session_cookie(client, "xyz789", cookie_name="auth_session")

    assert result.cookies.get("auth_session") == "xyz789"


def test_with_permissions_assigns_permissions_to_user() -> None:
    user = StubUser(id=1, pk=1)

    with_permissions(user, {"view_reports", "edit_users"})

    assert user.permissions == {"view_reports", "edit_users"}


def test_with_roles_assigns_roles_to_user() -> None:
    user = StubUser(id=1, pk=1)

    with_roles(user, {"admin", "moderator"})

    assert user.roles == {"admin", "moderator"}


def test_with_permissions_returns_the_same_user() -> None:
    user = StubUser(id=1, pk=1)

    result = with_permissions(user, {"perm"})

    assert result is user


def test_with_roles_returns_the_same_user() -> None:
    user = StubUser(id=1, pk=1)

    result = with_roles(user, {"editor"})

    assert result is user
