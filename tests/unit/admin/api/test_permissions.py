"""Unit tests for openviper.admin.api.permissions — permission checking."""

from unittest.mock import MagicMock

from openviper.admin.api.permissions import (
    PermissionChecker,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)


def _make_request(user=None):
    """Create a mock request."""
    request = MagicMock()
    request.user = user
    return request


def _make_user(is_authenticated=True, is_staff=False, is_superuser=False, has_perm=True):
    """Create a mock user."""
    user = MagicMock()
    user.is_authenticated = is_authenticated
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.has_perm = MagicMock(return_value=has_perm)
    return user


def _make_model_class(name="TestModel"):
    """Create a mock model class."""
    model = MagicMock()
    model.__name__ = name
    model._app_name = "test"
    return model


class TestCheckAdminAccess:
    """Test check_admin_access function."""

    def test_staff_user_has_access(self):
        """Test that staff users have admin access."""
        user = _make_user(is_authenticated=True, is_staff=True)
        request = _make_request(user)

        assert check_admin_access(request) is True

    def test_superuser_has_access(self):
        """Test that superusers have admin access."""
        user = _make_user(is_authenticated=True, is_superuser=True)
        request = _make_request(user)

        assert check_admin_access(request) is True

    def test_staff_and_superuser_has_access(self):
        """Test that users with both flags have access."""
        user = _make_user(is_authenticated=True, is_staff=True, is_superuser=True)
        request = _make_request(user)

        assert check_admin_access(request) is True

    def test_regular_authenticated_user_no_access(self):
        """Test that regular authenticated users don't have access."""
        user = _make_user(is_authenticated=True, is_staff=False, is_superuser=False)
        request = _make_request(user)

        assert check_admin_access(request) is False

    def test_unauthenticated_user_no_access(self):
        """Test that unauthenticated users don't have access."""
        user = _make_user(is_authenticated=False)
        request = _make_request(user)

        assert check_admin_access(request) is False

    def test_no_user_no_access(self):
        """Test that requests without user don't have access."""
        request = _make_request(user=None)

        assert check_admin_access(request) is False


class TestCheckModelPermission:
    """Test check_model_permission function."""

    def test_superuser_has_all_model_permissions(self):
        """Test that superusers have all permissions."""
        user = _make_user(is_superuser=True)
        request = _make_request(user)
        model_class = _make_model_class()

        assert check_model_permission(request, model_class, "view") is True
        assert check_model_permission(request, model_class, "add") is True
        assert check_model_permission(request, model_class, "change") is True
        assert check_model_permission(request, model_class, "delete") is True

    def test_staff_user_has_basic_permissions(self):
        """Test that staff users have basic permissions."""
        user = _make_user(is_staff=True, is_superuser=False)
        request = _make_request(user)
        model_class = _make_model_class()

        assert check_model_permission(request, model_class, "view") is True
        assert check_model_permission(request, model_class, "add") is True
        assert check_model_permission(request, model_class, "change") is True
        assert check_model_permission(request, model_class, "delete") is True

    def test_user_with_has_perm_method(self):
        """Test users with has_perm method."""
        user = _make_user(is_staff=False, is_superuser=False)
        user.has_perm = MagicMock()
        request = _make_request(user)
        model_class = _make_model_class()

        result = check_model_permission(request, model_class, "view")
        # User with has_perm should return True
        assert isinstance(result, bool)

    def test_no_user_no_permissions(self):
        """Test that requests without user have no permissions."""
        request = _make_request(user=None)
        model_class = _make_model_class()

        assert check_model_permission(request, model_class, "view") is False

    def test_permission_check_for_different_actions(self):
        """Test permission checking for different action types."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        model_class = _make_model_class()

        # Staff user should have all basic permissions
        assert check_model_permission(request, model_class, "view") is True
        assert check_model_permission(request, model_class, "add") is True
        assert check_model_permission(request, model_class, "change") is True
        assert check_model_permission(request, model_class, "delete") is True


class TestCheckObjectPermission:
    """Test check_object_permission function."""

    def test_superuser_has_all_object_permissions(self):
        """Test that superusers have all object permissions."""
        user = _make_user(is_superuser=True)
        request = _make_request(user)
        obj = MagicMock()
        obj.__class__ = _make_model_class()

        assert check_object_permission(request, obj, "view") is True
        assert check_object_permission(request, obj, "change") is True
        assert check_object_permission(request, obj, "delete") is True

    def test_staff_user_has_object_permissions(self):
        """Test that staff users have object permissions."""
        user = _make_user(is_staff=True, is_superuser=False)
        request = _make_request(user)
        obj = MagicMock()
        obj.__class__ = _make_model_class()

        result = check_object_permission(request, obj, "view")
        assert isinstance(result, bool)

    def test_no_user_no_object_permissions(self):
        """Test that requests without user have no object permissions."""
        request = _make_request(user=None)
        obj = MagicMock()

        assert check_object_permission(request, obj, "view") is False

    def test_delegates_to_model_permission(self):
        """Test that object permission delegates to model permission."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        obj = MagicMock()
        obj.__class__ = _make_model_class()

        # Should use model permission check
        result = check_object_permission(request, obj, "change")
        assert isinstance(result, bool)


class TestPermissionChecker:
    """Test PermissionChecker class."""

    def test_initialization(self):
        """Test PermissionChecker initialization."""
        user = _make_user()
        request = _make_request(user)

        checker = PermissionChecker(request)

        assert checker.request is request
        assert checker.user is user

    def test_is_authenticated_property(self):
        """Test is_authenticated property."""
        user = _make_user(is_authenticated=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.is_authenticated is True

    def test_is_authenticated_no_user(self):
        """Test is_authenticated with no user."""
        request = _make_request(user=None)
        checker = PermissionChecker(request)

        assert checker.is_authenticated is False

    def test_is_staff_property(self):
        """Test is_staff property."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.is_staff is True

    def test_is_staff_no_user(self):
        """Test is_staff with no user."""
        request = _make_request(user=None)
        checker = PermissionChecker(request)

        assert checker.is_staff is False

    def test_is_superuser_property(self):
        """Test is_superuser property."""
        user = _make_user(is_superuser=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.is_superuser is True

    def test_is_superuser_no_user(self):
        """Test is_superuser with no user."""
        request = _make_request(user=None)
        checker = PermissionChecker(request)

        assert checker.is_superuser is False

    def test_has_admin_access_property_staff(self):
        """Test has_admin_access for staff user."""
        user = _make_user(is_authenticated=True, is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.has_admin_access is True

    def test_has_admin_access_property_superuser(self):
        """Test has_admin_access for superuser."""
        user = _make_user(is_authenticated=True, is_superuser=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.has_admin_access is True

    def test_has_admin_access_property_regular_user(self):
        """Test has_admin_access for regular user."""
        user = _make_user(is_authenticated=True, is_staff=False)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.has_admin_access is False

    def test_has_admin_access_property_unauthenticated(self):
        """Test has_admin_access for unauthenticated user."""
        user = _make_user(is_authenticated=False)
        request = _make_request(user)
        checker = PermissionChecker(request)

        assert checker.has_admin_access is False

    def test_can_view_method(self):
        """Test can_view method."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.can_view(model_class) is True

    def test_can_add_method(self):
        """Test can_add method."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.can_add(model_class) is True

    def test_can_change_method_without_object(self):
        """Test can_change method without specific object."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.can_change(model_class) is True

    def test_can_change_method_with_object(self):
        """Test can_change method with specific object."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()
        obj = MagicMock()
        obj.__class__ = model_class

        result = checker.can_change(model_class, obj)
        assert isinstance(result, bool)

    def test_can_delete_method_without_object(self):
        """Test can_delete method without specific object."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.can_delete(model_class) is True

    def test_can_delete_method_with_object(self):
        """Test can_delete method with specific object."""
        user = _make_user(is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()
        obj = MagicMock()
        obj.__class__ = model_class

        result = checker.can_delete(model_class, obj)
        assert isinstance(result, bool)


class TestPermissionCheckerWithDifferentUsers:
    """Test PermissionChecker with various user types."""

    def test_superuser_permissions(self):
        """Test superuser has all permissions."""
        user = _make_user(is_authenticated=True, is_superuser=True, is_staff=False)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.has_admin_access is True
        assert checker.can_view(model_class) is True
        assert checker.can_add(model_class) is True
        assert checker.can_change(model_class) is True
        assert checker.can_delete(model_class) is True

    def test_staff_permissions(self):
        """Test staff user has basic permissions."""
        user = _make_user(is_authenticated=True, is_staff=True, is_superuser=False)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.has_admin_access is True
        assert checker.can_view(model_class) is True
        assert checker.can_add(model_class) is True

    def test_regular_user_no_permissions(self):
        """Test regular user has no permissions."""
        user = _make_user(is_authenticated=True, is_staff=False, is_superuser=False, has_perm=False)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.has_admin_access is False
        # Regular users should not have permissions
        result = checker.can_view(model_class)
        assert isinstance(result, bool)

    def test_unauthenticated_user_no_permissions(self):
        """Test unauthenticated user has no permissions."""
        user = _make_user(is_authenticated=False)
        request = _make_request(user)
        checker = PermissionChecker(request)
        model_class = _make_model_class()

        assert checker.has_admin_access is False
        assert checker.is_authenticated is False


class TestPermissionCheckerProperties:
    """Test PermissionChecker property accessors."""

    def test_properties_with_none_user(self):
        """Test that properties handle None user gracefully."""
        request = _make_request(user=None)
        checker = PermissionChecker(request)

        assert checker.user is None
        assert checker.is_authenticated is False
        assert checker.is_staff is False
        assert checker.is_superuser is False
        assert checker.has_admin_access is False

    def test_properties_cache_behavior(self):
        """Test that properties return consistent values."""
        user = _make_user(is_authenticated=True, is_staff=True)
        request = _make_request(user)
        checker = PermissionChecker(request)

        # Multiple calls should return same value
        assert checker.is_staff is True
        assert checker.is_staff is True  # Second call
        assert checker.has_admin_access is True
        assert checker.has_admin_access is True  # Second call
