"""Unit tests for openviper.auth.models module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth._user_cache import _USER_CACHE, invalidate_user_cache
from openviper.auth.models import (
    AnonymousUser,
    Permission,
    Role,
    User,
    _on_user_update,
)
from openviper.core.context import request_perms_cache


class TestPermissionModel:
    """Tests for Permission model."""

    def test_str_returns_codename(self):
        """Should return codename as string representation."""
        perm = Permission()
        perm.codename = "post.create"
        assert str(perm) == "post.create"

    def test_str_handles_none_codename(self):
        """Should handle None codename."""
        perm = Permission()
        perm.codename = None
        assert str(perm) == ""

    def test_has_correct_table_name(self):
        """Should use correct table name."""
        assert Permission.Meta.table_name == "auth_permissions"


class TestRoleModel:
    """Tests for Role model."""

    def test_str_returns_name(self):
        """Should return name as string representation."""
        role = Role()
        role.name = "admin"
        assert str(role) == "admin"

    def test_str_handles_none_name(self):
        """Should handle None name."""
        role = Role()
        role.name = None
        assert str(role) == ""

    def test_has_correct_table_name(self):
        """Should use correct table name."""
        assert Role.Meta.table_name == "auth_roles"


class TestAbstractUserPasswordMethods:
    """Tests for AbstractUser password methods."""

    @pytest.mark.asyncio
    async def test_set_password_hashes_password(self):
        """Should hash password using make_password."""

        user = User()

        with patch(
            "openviper.auth.models.make_password", new=AsyncMock(return_value="argon2$hashed")
        ):
            await user.set_password("my_password")

        assert user.password == "argon2$hashed"

    @pytest.mark.asyncio
    async def test_check_password_verifies_correct_password(self):
        """Should return True for correct password."""

        user = User()
        user.password = "argon2$hashed_password"

        with patch("openviper.auth.models.check_password", new=AsyncMock(return_value=True)):
            result = await user.check_password("correct_password")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_password_rejects_incorrect_password(self):
        """Should return False for incorrect password."""

        user = User()
        user.password = "argon2$hashed_password"

        with patch("openviper.auth.models.check_password", new=AsyncMock(return_value=False)):
            result = await user.check_password("wrong_password")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_password_returns_false_when_no_password_set(self):
        """Should return False when password is not set."""

        user = User()
        user.password = None

        result = await user.check_password("any_password")
        assert result is False


class TestAbstractUserAuthenticationProperties:
    """Tests for AbstractUser authentication properties."""

    def test_is_authenticated_returns_true(self):
        """Should return True for authenticated users."""

        user = User()
        assert user.is_authenticated is True

    def test_is_anonymous_returns_false(self):
        """Should return False for authenticated users."""

        user = User()
        assert user.is_anonymous is False


class TestAbstractUserPermissionMethods:
    """Tests for AbstractUser permission checking methods."""

    @pytest.mark.asyncio
    async def test_has_perm_returns_true_for_superuser(self):
        """Superusers should have all permissions."""

        user = User()
        user.is_superuser = True

        result = await user.has_perm("any.permission")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_perm_checks_permissions_for_regular_user(self):
        """Should check permissions for regular users."""

        user = User()
        user.is_superuser = False

        with patch.object(user, "get_permissions", new=AsyncMock(return_value={"post.create"})):
            assert await user.has_perm("post.create") is True
            assert await user.has_perm("post.delete") is False

    @pytest.mark.asyncio
    async def test_has_role_returns_true_for_superuser(self):
        """Superusers should have all roles."""

        user = User()
        user.is_superuser = True

        result = await user.has_role("admin")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_role_checks_assigned_roles(self):
        """Should check assigned roles for regular users."""

        user = User()
        user.is_superuser = False
        user.id = 1

        mock_role = MagicMock()
        mock_role.name = "admin"

        with patch.object(user, "get_roles", new=AsyncMock(return_value=[mock_role])):
            result = await user.has_role("admin")
            assert result is True

    @pytest.mark.asyncio
    async def test_has_model_perm_returns_true_for_superuser(self):
        """Superusers should have all model permissions."""

        user = User()
        user.is_superuser = True

        result = await user.has_model_perm("app.Model", "delete")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_permissions_returns_all_for_superuser(self):
        """Superusers should get all permissions."""

        user = User()
        user.id = 99
        user.is_superuser = True

        with patch(
            "openviper.auth.models.Permission.objects.values_list",
            new=AsyncMock(return_value=["perm1", "perm2"]),
        ):
            perms = await user.get_permissions()
            assert perms == {"perm1", "perm2"}

    @pytest.mark.asyncio
    async def test_get_permissions_uses_cache(self):
        """Should use cached permissions if available in the request ContextVar."""

        user = User()
        user.id = 1

        token = request_perms_cache.set({1: {"cached.perm"}})
        try:
            perms = await user.get_permissions()
            assert perms == {"cached.perm"}
        finally:
            request_perms_cache.reset(token)


class TestAbstractUserRoleMethods:
    """Tests for AbstractUser role management methods."""

    @pytest.mark.asyncio
    async def test_assign_role_creates_user_role(self):
        """Should create UserRole entry when assigning role."""

        user = User()
        user.id = 1

        mock_role = MagicMock()
        mock_role.pk = 2

        with patch("openviper.auth.models.UserRole.objects.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)

            with patch(
                "openviper.auth.models.UserRole.objects.create", new=AsyncMock()
            ) as mock_create:
                await user.assign_role(mock_role)
                mock_create.assert_called_once_with(user=1, role=2)

    @pytest.mark.asyncio
    async def test_assign_role_skips_if_already_assigned(self):
        """Should not create duplicate UserRole entries."""

        user = User()
        user.id = 1

        mock_role = MagicMock()
        mock_role.pk = 2

        existing_user_role = MagicMock()

        with patch("openviper.auth.models.UserRole.objects.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=existing_user_role)

            with patch(
                "openviper.auth.models.UserRole.objects.create", new=AsyncMock()
            ) as mock_create:
                await user.assign_role(mock_role)
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_role_deletes_user_role(self):
        """Should delete UserRole entry when removing role."""

        user = User()
        user.id = 1

        mock_role = MagicMock()
        mock_role.pk = 2

        mock_ur = MagicMock()
        mock_ur.delete = AsyncMock()

        with patch("openviper.auth.models.UserRole.objects.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=mock_ur)
            await user.remove_role(mock_role)
            mock_ur.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_roles_returns_roles_from_role_profile(self):
        """Should return roles from role_profile if set."""

        user = User()
        user.role_profile = MagicMock()
        user.role_profile.pk = 1

        # Create a mock that passes isinstance(role_id, Role) check
        mock_role = MagicMock(spec=Role)
        mock_role.name = "admin"
        mock_detail = MagicMock()
        mock_detail.role = mock_role

        with patch("openviper.auth.models.RoleProfileDetail.objects.filter") as mock_filter:
            mock_filter.return_value.select_related.return_value.all = AsyncMock(
                return_value=[mock_detail]
            )

            roles = await user.get_roles()
            assert mock_role in roles

    @pytest.mark.asyncio
    async def test_get_roles_returns_user_roles_when_no_profile(self):
        """Should return direct user roles when no profile is set."""

        user = User()
        user.role_profile = None
        user.id = 1

        # Create a mock that passes isinstance(role_id, Role) check
        mock_role = MagicMock(spec=Role)
        mock_role.name = "editor"
        mock_user_role = MagicMock()
        mock_user_role.role = mock_role

        with patch("openviper.auth.models.UserRole.objects.filter") as mock_filter:
            mock_filter.return_value.select_related.return_value.all = AsyncMock(
                return_value=[mock_user_role]
            )

            roles = await user.get_roles()
            assert mock_role in roles


class TestAbstractUserStringRepresentation:
    """Tests for AbstractUser string methods."""

    def test_full_name_combines_first_and_last_name(self):
        """Should combine first and last name."""

        user = User()
        user.first_name = "John"
        user.last_name = "Doe"

        assert user.full_name == "John Doe"

    def test_full_name_handles_missing_first_name(self):
        """Should handle missing first name."""

        user = User()
        user.first_name = None
        user.last_name = "Doe"

        assert user.full_name == "Doe"

    def test_full_name_handles_missing_last_name(self):
        """Should handle missing last name."""

        user = User()
        user.first_name = "John"
        user.last_name = None

        assert user.full_name == "John"

    def test_full_name_returns_empty_when_both_missing(self):
        """Should return empty string when both names are missing."""

        user = User()
        user.first_name = None
        user.last_name = None

        assert user.full_name == ""

    def test_str_returns_username(self):
        """Should return username as string representation."""

        user = User()
        user.username = "testuser"

        assert str(user) == "testuser"

    def test_repr_includes_id_and_username(self):
        """Should include id and username in repr."""

        user = User()
        user.id = 42
        user.username = "testuser"

        assert repr(user) == "<User id=42 username='testuser'>"


class TestAnonymousUser:
    """Tests for AnonymousUser sentinel object."""

    def test_is_authenticated_is_false(self):
        """Should not be authenticated."""
        user = AnonymousUser()
        assert user.is_authenticated is False

    def test_is_anonymous_is_true(self):
        """Should be anonymous."""
        user = AnonymousUser()
        assert user.is_anonymous is True

    def test_is_active_is_false(self):
        """Should not be active."""
        user = AnonymousUser()
        assert user.is_active is False

    def test_is_superuser_is_false(self):
        """Should not be superuser."""
        user = AnonymousUser()
        assert user.is_superuser is False

    def test_is_staff_is_false(self):
        """Should not be staff."""
        user = AnonymousUser()
        assert user.is_staff is False

    def test_pk_is_none(self):
        """Should have None pk."""
        user = AnonymousUser()
        assert user.pk is None

    def test_id_is_none(self):
        """Should have None id."""
        user = AnonymousUser()
        assert user.id is None

    def test_username_is_empty(self):
        """Should have empty username."""
        user = AnonymousUser()
        assert user.username == ""

    def test_email_is_empty(self):
        """Should have empty email."""
        user = AnonymousUser()
        assert user.email == ""

    @pytest.mark.asyncio
    async def test_has_perm_returns_false(self):
        """Should not have any permissions."""
        user = AnonymousUser()
        assert await user.has_perm("any.perm") is False

    @pytest.mark.asyncio
    async def test_has_model_perm_returns_false(self):
        """Should not have any model permissions."""
        user = AnonymousUser()
        assert await user.has_model_perm("app.Model", "read") is False

    @pytest.mark.asyncio
    async def test_has_role_returns_false(self):
        """Should not have any roles."""
        user = AnonymousUser()
        assert await user.has_role("admin") is False

    @pytest.mark.asyncio
    async def test_get_permissions_returns_empty_set(self):
        """Should return empty permissions set."""
        user = AnonymousUser()
        assert await user.get_permissions() == set()

    def test_bool_returns_false(self):
        """Should be falsy in boolean context."""
        user = AnonymousUser()
        assert bool(user) is False

    def test_repr(self):
        """Should have descriptive repr."""
        user = AnonymousUser()
        assert repr(user) == "AnonymousUser"


class TestOnUserUpdate:
    """User.on_update model event evicts the user from the in-process auth cache."""

    def test_invalidate_user_cache_called_with_user_pk(self) -> None:
        """Event handler calls invalidate_user_cache with the instance pk."""
        instance = MagicMock()
        instance.pk = 42
        with patch("openviper.auth.models.invalidate_user_cache") as mock_invalidate:
            _on_user_update(instance, event="on_update")
            mock_invalidate.assert_called_once_with(42)

    def test_no_call_when_pk_is_none(self) -> None:
        """Event handler does nothing when the instance has no pk."""
        instance = MagicMock()
        instance.pkg = None
        instance.pk = None
        with patch("openviper.auth.models.invalidate_user_cache") as mock_invalidate:
            _on_user_update(instance, event="on_update")
            mock_invalidate.assert_not_called()

    def test_invalidate_user_cache_removes_entry(self) -> None:
        """invalidate_user_cache pops the user id from _USER_CACHE."""
        _USER_CACHE[99] = (MagicMock(), 9999999.0)
        assert 99 in _USER_CACHE
        invalidate_user_cache(99)
        assert 99 not in _USER_CACHE

    def test_invalidate_user_cache_noop_for_missing_id(self) -> None:
        """invalidate_user_cache does not raise when the id is absent."""
        _USER_CACHE.pop(1000, None)
        invalidate_user_cache(1000)  # must not raise
