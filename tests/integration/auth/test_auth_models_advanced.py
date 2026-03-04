"""Integration tests for advanced auth model functionality (roles, permissions, etc.)."""

from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from openviper.db.connection import close_db, init_db

    await init_db(drop_first=True)
    yield
    await close_db()


# ---------------------------------------------------------------------------
# User permission methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superuser_has_all_permissions():
    """Superuser get_permissions returns all permission codenames."""
    from openviper.auth.models import Permission, User

    # Create a permission
    perm = Permission(codename="can_edit", name="Can edit")
    await perm.save()

    # Create superuser
    user = User(username="super_perms", email="sp@example.com", is_active=True, is_superuser=True)
    user.set_password("pass123")
    await user.save()

    perms = await user.get_permissions()
    assert "can_edit" in perms


@pytest.mark.asyncio
async def test_regular_user_no_roles_has_no_permissions():
    """User with no roles has empty permissions."""
    from openviper.auth.models import User

    user = User(username="noperms", email="np@example.com", is_active=True, is_superuser=False)
    user.set_password("pass123")
    await user.save()

    perms = await user.get_permissions()
    assert perms == set()


@pytest.mark.asyncio
async def test_user_get_roles_via_user_role():
    """User with UserRole assignments returns correct roles."""
    from openviper.auth.models import Role, User

    user = User(username="roleuser", email="ru@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    role = Role(name="editor", description="Can edit")
    await role.save()

    await user.assign_role(role)

    roles = await user.get_roles()
    assert any(r.name == "editor" for r in roles)


@pytest.mark.asyncio
async def test_user_has_role_returns_true_when_assigned():
    """has_role returns True for roles the user has."""
    from openviper.auth.models import Role, User

    user = User(username="hasrole_user", email="hr@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    role = Role(name="moderator", description="Can moderate")
    await role.save()

    await user.assign_role(role)

    assert await user.has_role("moderator") is True


@pytest.mark.asyncio
async def test_user_has_role_returns_false_when_not_assigned():
    """has_role returns False for roles the user doesn't have."""
    from openviper.auth.models import User

    user = User(username="norole_user", email="nr@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    assert await user.has_role("admin") is False


@pytest.mark.asyncio
async def test_superuser_has_role_always_true():
    """Superuser has_role always returns True."""
    from openviper.auth.models import User

    user = User(username="super_role", email="sr@example.com", is_active=True, is_superuser=True)
    user.set_password("pass123")
    await user.save()

    assert await user.has_role("any_role") is True


@pytest.mark.asyncio
async def test_assign_role_no_duplicate():
    """Assigning same role twice doesn't create duplicate."""
    from openviper.auth.models import Role, User, UserRole

    user = User(username="dedup_user", email="dd@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    role = Role(name="dedup_role", description="")
    await role.save()

    # Assign twice
    await user.assign_role(role)
    await user.assign_role(role)

    # Should only have one UserRole
    user_roles = await UserRole.objects.filter(user=user.pk, role=role.pk).all()
    assert len(user_roles) == 1


@pytest.mark.asyncio
async def test_remove_role():
    """User can have role removed."""
    from openviper.auth.models import Role, User, UserRole

    user = User(username="remrole_user", email="rr@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    role = Role(name="temp_role", description="")
    await role.save()

    await user.assign_role(role)
    await user.remove_role(role)

    user_roles = await UserRole.objects.filter(user=user.pk, role=role.pk).all()
    assert len(user_roles) == 0


@pytest.mark.asyncio
async def test_user_permissions_via_role():
    """User gets permissions from assigned roles."""
    from openviper.auth.models import Permission, Role, RolePermission, User

    user = User(
        username="perm_via_role", email="pvr@example.com", is_active=True, is_superuser=False
    )
    user.set_password("pass123")
    await user.save()

    role = Role(name="writer", description="Can write")
    await role.save()

    perm = Permission(codename="can_write_posts", name="Can write posts")
    await perm.save()

    rp = RolePermission(role=role.pk, permission=perm.pk)
    await rp.save()

    await user.assign_role(role)

    perms = await user.get_permissions()
    assert "can_write_posts" in perms


@pytest.mark.asyncio
async def test_has_perm_returns_true_for_superuser():
    """Superuser has_perm always returns True."""
    from openviper.auth.models import User

    user = User(username="su_perm", email="sup@example.com", is_active=True, is_superuser=True)
    user.set_password("pass123")
    await user.save()

    assert await user.has_perm("any_codename") is True


@pytest.mark.asyncio
async def test_has_perm_returns_false_for_missing_perm():
    """Regular user without the permission returns False."""
    from openviper.auth.models import User

    user = User(
        username="no_perm_user", email="npu@example.com", is_active=True, is_superuser=False
    )
    user.set_password("pass123")
    await user.save()

    assert await user.has_perm("not_granted_perm") is False


@pytest.mark.asyncio
async def test_check_password_with_no_hash():
    """User with no password set returns False on check_password."""
    from openviper.auth.models import User

    user = User(username="nopass_user", email="nopass@example.com", is_active=True)
    # Explicitly no password set
    user.password = None

    result = user.check_password("anything")
    assert result is False


# ---------------------------------------------------------------------------
# AnonymousUser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anonymous_user_has_perm_always_false():
    from openviper.auth.models import AnonymousUser

    anon = AnonymousUser()
    assert await anon.has_perm("any_perm") is False


@pytest.mark.asyncio
async def test_anonymous_user_has_model_perm_always_false():
    from openviper.auth.models import AnonymousUser

    anon = AnonymousUser()
    assert await anon.has_model_perm("app.Model", "read") is False


@pytest.mark.asyncio
async def test_anonymous_user_has_role_always_false():
    from openviper.auth.models import AnonymousUser

    anon = AnonymousUser()
    assert await anon.has_role("admin") is False


@pytest.mark.asyncio
async def test_anonymous_user_get_permissions_returns_empty():
    from openviper.auth.models import AnonymousUser

    anon = AnonymousUser()
    perms = await anon.get_permissions()
    assert perms == set()


# ---------------------------------------------------------------------------
# User full_name property
# ---------------------------------------------------------------------------


def test_user_full_name_with_both_names():
    from openviper.auth.models import User

    user = User(username="jd", email="jd@e.com", first_name="John", last_name="Doe")
    assert user.full_name == "John Doe"


def test_user_full_name_first_only():
    from openviper.auth.models import User

    user = User(username="j", email="j@e.com", first_name="John", last_name="")
    assert user.full_name == "John"


def test_user_full_name_empty():
    from openviper.auth.models import User

    user = User(username="u", email="u@e.com", first_name="", last_name="")
    assert user.full_name == ""


# ---------------------------------------------------------------------------
# User str/repr
# ---------------------------------------------------------------------------


def test_user_str_returns_username():
    from openviper.auth.models import User

    user = User(username="struser", email="s@e.com")
    assert str(user) == "struser"


def test_user_repr_contains_username():
    from openviper.auth.models import User

    user = User(username="repruser", email="r@e.com")
    assert "repruser" in repr(user)


# ---------------------------------------------------------------------------
# User get_roles when no roles exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_get_roles_empty():
    """User with no roles returns empty list."""
    from openviper.auth.models import User

    user = User(username="empty_roles", email="er@example.com", is_active=True)
    user.set_password("pass123")
    await user.save()

    roles = await user.get_roles()
    assert roles == []
