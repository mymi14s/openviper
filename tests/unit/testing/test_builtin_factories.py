"""Tests for OpenViper's pre-built model factories (UserFactory, etc.)."""

from __future__ import annotations

from openviper.auth import get_user_model
from openviper.auth.hashers import is_password_usable
from openviper.auth.models import Permission, Role
from openviper.testing.factories import (
    PermissionFactory,
    RoleFactory,
    SuperuserFactory,
    UserFactory,
)

# ── UserFactory ───────────────────────────────────────────────────────────


def test_user_factory_build_returns_user_model_instance() -> None:
    UserModel = get_user_model()

    user = UserFactory.build()

    assert isinstance(user, UserModel)


def test_user_factory_build_generates_unique_usernames() -> None:
    first = UserFactory.build()
    second = UserFactory.build()

    assert first.username != second.username


def test_user_factory_build_generates_unique_emails() -> None:
    first = UserFactory.build()
    second = UserFactory.build()

    assert first.email != second.email


def test_user_factory_build_sets_sensible_defaults() -> None:
    user = UserFactory.build()

    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False


def test_user_factory_build_stores_unusable_password_placeholder() -> None:
    user = UserFactory.build()

    # build() cannot hash passwords (async); stores an unusable placeholder.
    assert not is_password_usable(user.password)


def test_user_factory_build_respects_field_overrides() -> None:
    user = UserFactory.build(email="custom@example.com", first_name="Alice")

    assert user.email == "custom@example.com"
    assert user.first_name == "Alice"


def test_user_factory_build_batch_returns_list_of_correct_length() -> None:
    users = UserFactory.build_batch(3)

    assert len(users) == 3


def test_user_factory_build_batch_produces_unique_emails() -> None:
    users = UserFactory.build_batch(5)
    emails = {u.email for u in users}

    assert len(emails) == 5


# ── SuperuserFactory ──────────────────────────────────────────────────────


def test_superuser_factory_build_returns_superuser_flags() -> None:
    admin = SuperuserFactory.build()

    assert admin.is_staff is True
    assert admin.is_superuser is True


def test_superuser_factory_build_uses_admin_username_sequence() -> None:
    admin = SuperuserFactory.build()

    assert admin.username.startswith("admin")


def test_superuser_factory_is_distinct_from_regular_user_factory() -> None:
    user = UserFactory.build()
    admin = SuperuserFactory.build()

    assert not user.is_superuser
    assert admin.is_superuser


# ── PermissionFactory ─────────────────────────────────────────────────────


def test_permission_factory_build_returns_permission_instance() -> None:
    perm = PermissionFactory.build()

    assert isinstance(perm, Permission)


def test_permission_factory_build_generates_unique_codenames() -> None:
    first = PermissionFactory.build()
    second = PermissionFactory.build()

    assert first.codename != second.codename


def test_permission_factory_build_respects_codename_override() -> None:
    perm = PermissionFactory.build(codename="view_dashboard")

    assert perm.codename == "view_dashboard"


# ── RoleFactory ───────────────────────────────────────────────────────────


def test_role_factory_build_returns_role_instance() -> None:
    role = RoleFactory.build()

    assert isinstance(role, Role)


def test_role_factory_build_generates_unique_names() -> None:
    first = RoleFactory.build()
    second = RoleFactory.build()

    assert first.name != second.name


def test_role_factory_build_sets_default_description() -> None:
    role = RoleFactory.build()

    assert role.description == "Test role"


def test_role_factory_build_respects_name_override() -> None:
    role = RoleFactory.build(name="editors")

    assert role.name == "editors"
