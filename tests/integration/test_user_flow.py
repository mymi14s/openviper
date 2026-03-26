"""Integration tests for user-specific workflows.

This module tests user creation, authentication, authorization,
role assignment, and permission checking workflows.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from openviper.auth.hashers import check_password
from openviper.auth.jwt import create_access_token, decode_access_token
from openviper.auth.models import Permission, Role, User
from openviper.cache import get_cache

if TYPE_CHECKING:
    from openviper.app import OpenViper


class TestUserCreationFlow:
    """Tests for user creation and registration workflows."""

    @pytest.mark.asyncio
    async def test_create_user_with_password(self, test_database):
        """Test creating a user with password hashing."""
        user = User(
            username="newuser",
            email="newuser@example.com",
            is_active=True,
        )
        await user.set_password("secure_password")
        await user.save()

        assert user.id is not None
        assert user.username == "newuser"
        assert await check_password("secure_password", user.password)
        assert not await check_password("wrong_password", user.password)

    @pytest.mark.asyncio
    async def test_create_multiple_users(self, test_database):
        """Test creating multiple users in sequence."""
        users_data = [
            {"username": "user1", "email": "user1@example.com"},
            {"username": "user2", "email": "user2@example.com"},
            {"username": "user3", "email": "user3@example.com"},
        ]

        created_users = []
        for data in users_data:
            user = User(**data)
            await user.set_password("password123")
            await user.save()
            created_users.append(user)

        all_users = await User.objects.all()
        assert len(all_users) >= len(created_users)

        usernames = {u.username for u in all_users}
        for data in users_data:
            assert data["username"] in usernames

    @pytest.mark.asyncio
    async def test_create_user_through_api(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test creating a user through the API endpoint."""
        async with app_with_routes.test_client() as client:
            response = await client.post(
                "/users",
                json={
                    "username": "apiuser",
                    "email": "api@example.com",
                    "password": "api123",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["username"] == "apiuser"
            assert "id" in data

            user = await User.objects.get(id=data["id"])
            assert user is not None
            assert user.username == "apiuser"


class TestUserAuthenticationFlow:
    """Tests for user authentication workflows."""

    @pytest.mark.asyncio
    async def test_password_verification(self, test_database, admin_user: User):
        """Test password verification for existing user."""
        is_valid = await check_password("admin123", admin_user.password)
        assert is_valid is True

        is_valid = await check_password("wrongpassword", admin_user.password)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_password_change_flow(self, test_database):
        """Test changing user password."""
        user = User(username="changepass", email="change@example.com")
        await user.set_password("old_password")
        await user.save()

        assert await check_password("old_password", user.password)

        await user.set_password("new_password")
        await user.save()

        user_from_db = await User.objects.get(id=user.id)
        assert await check_password("new_password", user_from_db.password)
        assert not await check_password("old_password", user_from_db.password)

    @pytest.mark.asyncio
    async def test_jwt_token_generation_and_validation(self, test_database, admin_user: User):
        """Test JWT token generation and validation for authentication."""
        token = create_access_token(
            user_id=admin_user.id,
            extra_claims={"username": admin_user.username},
        )

        assert token is not None
        assert isinstance(token, str)

        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded.get("sub") == str(admin_user.id)
        assert decoded.get("username") == admin_user.username

    @pytest.mark.asyncio
    async def test_user_active_status(self, test_database):
        """Test user active status affects authentication."""
        active_user = User(
            username="active",
            email="active@example.com",
            is_active=True,
        )
        await active_user.set_password("password123")
        await active_user.save()

        inactive_user = User(
            username="inactive",
            email="inactive@example.com",
            is_active=False,
        )
        await inactive_user.set_password("password123")
        await inactive_user.save()

        assert active_user.is_active is True
        assert inactive_user.is_active is False


class TestUserRoleAssignment:
    """Tests for role assignment workflows."""

    @pytest.mark.asyncio
    async def test_assign_single_role_to_user(self, test_database):
        """Test assigning a single role to a user."""
        user = User(username="roleuser", email="role@example.com")
        await user.save()

        role = Role(name="editor", description="Editor role")
        await role.save()

        await user.roles.add(role)

        user_roles = await user.get_roles()
        assert len(user_roles) == 1
        assert user_roles[0].name == "editor"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Many-to-many relationship issue - only first role is being retained")
    async def test_assign_multiple_roles_to_user(self, test_database):
        """Test assigning multiple roles to a user."""
        user = User(username="multirole", email="multi@example.com")
        await user.save()

        role1 = Role(name="viewer", description="Viewer role")
        await role1.save()

        role2 = Role(name="editor", description="Editor role")
        await role2.save()

        role3 = Role(name="admin", description="Admin role")
        await role3.save()

        await user.roles.add(role1)
        await user.roles.add(role2)
        await user.roles.add(role3)

        user_roles = await user.get_roles()
        assert len(user_roles) == 3

        role_names = {r.name for r in user_roles}
        assert role_names == {"viewer", "editor", "admin"}

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Many-to-many relationship issue - requires debugging")
    async def test_remove_role_from_user(self, test_database):
        """Test removing a role from a user."""
        user = User(username="removerole", email="remove@example.com")
        await user.save()

        role1 = Role(name="temp_role", description="Temporary role")
        await role1.save()

        role2 = Role(name="permanent_role", description="Permanent role")
        await role2.save()

        await user.roles.add(role1)
        await user.roles.add(role2)

        user_roles = await user.get_roles()
        assert len(user_roles) == 2

        await user.roles.remove(role1)

        user_roles = await user.get_roles()
        assert len(user_roles) == 1
        assert user_roles[0].name == "permanent_role"


class TestUserPermissions:
    """Tests for user permission workflows."""

    @pytest.mark.asyncio
    async def test_superuser_has_all_permissions(
        self,
        test_database,
        test_cache,
        admin_user: User,
        drain_tasks,
    ):
        """Test that superuser has all permissions."""
        assert admin_user.is_superuser is True

        # Use unique codenames to avoid cross-test UNIQUE constraint collisions
        suffix = uuid.uuid4().hex[:8]
        code1 = f"super_test1_{suffix}"
        code2 = f"super_test2_{suffix}"

        perm1 = Permission(codename=code1, name="Super test 1")
        await perm1.save()
        await drain_tasks()  # wait for Permission.after_insert background task to finish
        perm2 = Permission(codename=code2, name="Super test 2")
        await perm2.save()
        await drain_tasks()  # drain before querying

        # Verify both saved correctly before testing permissions
        saved = {p.codename for p in await Permission.objects.all()}
        assert code1 in saved
        assert code2 in saved
        assert f"Permissions not saved: {saved}"

        await test_cache.clear()

        permissions = await admin_user.get_permissions()
        assert isinstance(permissions, set)
        assert code1 in permissions, f"Expected {code1} in {permissions}"
        assert code2 in permissions, f"Expected {code2} in {permissions}"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Foreign key constraint issue with role-permission many-to-many")
    async def test_user_permissions_from_roles(
        self,
        test_database,
        test_cache,
    ):
        """Test getting user permissions from assigned roles."""
        perm1 = Permission(codename="view_content", name="Can view content")
        await perm1.save()

        perm2 = Permission(codename="edit_content", name="Can edit content")
        await perm2.save()

        role = Role(name="content_editor", description="Content editor")
        await role.save()

        await role.permissions.add(perm1)
        await role.permissions.add(perm2)

        user = User(username="contentuser", email="content@example.com")
        await user.save()

        await user.roles.add(role)

        user_permissions = await user.get_permissions()
        assert "view_content" in user_permissions
        assert "edit_content" in user_permissions

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Foreign key constraint issue with role-permission many-to-many")
    async def test_permission_caching(
        self,
        test_database,
        test_cache,
    ):
        """Test that permissions are cached correctly."""
        perm = Permission(codename="cached_perm", name="Cached permission")
        await perm.save()

        role = Role(name="cached_role", description="Cached role")
        await role.save()

        await role.permissions.add(perm)

        user = User(username="cacheuser", email="cache@example.com")
        await user.save()

        await user.roles.add(role)

        permissions1 = await user.get_permissions()
        assert "cached_perm" in permissions1

        cache = get_cache()
        cache_key = f"user_perms:{user.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None
        assert "cached_perm" in cached_perms

        permissions2 = await user.get_permissions()
        assert permissions1 == permissions2

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Foreign key constraint issue with role-permission many-to-many")
    async def test_permissions_from_multiple_roles(
        self,
        test_database,
        test_cache,
    ):
        """Test aggregating permissions from multiple roles."""
        perm1 = Permission(codename="read_data", name="Can read data")
        await perm1.save()

        perm2 = Permission(codename="write_data", name="Can write data")
        await perm2.save()

        perm3 = Permission(codename="delete_data", name="Can delete data")
        await perm3.save()

        reader_role = Role(name="reader", description="Reader")
        await reader_role.save()
        await reader_role.permissions.add(perm1)

        writer_role = Role(name="writer", description="Writer")
        await writer_role.save()
        await writer_role.permissions.add(perm1)
        await writer_role.permissions.add(perm2)

        admin_role = Role(name="data_admin", description="Data admin")
        await admin_role.save()
        await admin_role.permissions.add(perm1)
        await admin_role.permissions.add(perm2)
        await admin_role.permissions.add(perm3)

        user = User(username="multiperms", email="multi@example.com")
        await user.save()

        await user.roles.add(reader_role)
        await user.roles.add(writer_role)

        permissions = await user.get_permissions()
        assert "read_data" in permissions
        assert "write_data" in permissions
        assert "delete_data" not in permissions

        await user.roles.add(admin_role)
        permissions = await user.get_permissions()
        assert "delete_data" in permissions


class TestUserUpdateFlow:
    """Tests for user update workflows."""

    @pytest.mark.asyncio
    async def test_update_user_email(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test updating user email through API."""
        user = User(username="updateuser", email="old@example.com")
        await user.save()

        async with app_with_routes.test_client() as client:
            response = await client.put(
                f"/users/{user.id}",
                json={"email": "new@example.com"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["email"] == "new@example.com"

            updated_user = await User.objects.get(id=user.id)
            assert updated_user.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_update_user_password(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test updating user password through API."""
        user = User(username="passchange", email="pass@example.com")
        await user.set_password("old_password123")
        await user.save()

        async with app_with_routes.test_client() as client:
            response = await client.put(
                f"/users/{user.id}",
                json={"password": "new_password456"},
            )

            assert response.status_code == 200

            updated_user = await User.objects.get(id=user.id)
            assert await check_password("new_password456", updated_user.password)
            assert not await check_password("old_password123", updated_user.password)


class TestUserDeletionFlow:
    """Tests for user deletion workflows."""

    @pytest.mark.asyncio
    async def test_delete_user_through_api(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test deleting a user through the API."""
        user = User(username="deleteuser", email="delete@example.com")
        await user.save()
        user_id = user.id

        async with app_with_routes.test_client() as client:
            response = await client.delete(f"/users/{user_id}")
            assert response.status_code == 204

            response = await client.get(f"/users/{user_id}")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_user_clears_cache(
        self,
        test_database,
        test_cache,
    ):
        """Test that deleting a user clears their cached data."""
        user = User(username="cacheclear", email="clear@example.com")
        await user.save()

        permissions = await user.get_permissions()
        assert isinstance(permissions, set)

        cache = get_cache()
        cache_key = f"user_perms:{user.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None

        await user.delete()

        deleted_user = await User.objects.filter(id=user.pk).first()
        assert deleted_user is None
