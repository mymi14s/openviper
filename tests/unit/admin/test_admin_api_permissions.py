"""Unit tests for openviper.admin.api.permissions."""

from unittest.mock import MagicMock

import pytest

from openviper.admin.api.permissions import (
    PermissionChecker,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user):
    request = MagicMock()
    request.user = user
    return request


def _staff_user():
    user = MagicMock()
    user.is_authenticated = True
    user.is_staff = True
    user.is_superuser = False
    return user


def _superuser():
    user = MagicMock()
    user.is_authenticated = True
    user.is_staff = False
    user.is_superuser = True
    return user


def _plain_user(has_has_perm=True):
    """Authenticated, non-staff, non-superuser user."""
    if has_has_perm:
        user = MagicMock()
    else:
        user = MagicMock(spec=["is_authenticated", "is_staff", "is_superuser"])
    user.is_authenticated = True
    user.is_staff = False
    user.is_superuser = False
    return user


# ---------------------------------------------------------------------------
# check_admin_access
# ---------------------------------------------------------------------------


class TestCheckAdminAccess:
    def test_request_has_no_user_attribute(self):
        """request object with no 'user' attribute returns False."""
        request = object()
        assert check_admin_access(request) is False

    def test_user_is_none(self):
        assert check_admin_access(_make_request(None)) is False

    def test_user_not_authenticated(self):
        user = MagicMock()
        user.is_authenticated = False
        user.is_staff = True
        user.is_superuser = False
        assert check_admin_access(_make_request(user)) is False

    def test_user_authenticated_not_staff_not_superuser(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_staff = False
        user.is_superuser = False
        assert check_admin_access(_make_request(user)) is False

    def test_user_is_staff(self):
        assert check_admin_access(_make_request(_staff_user())) is True

    def test_user_is_superuser(self):
        assert check_admin_access(_make_request(_superuser())) is True

    def test_user_is_staff_and_superuser(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_staff = True
        user.is_superuser = True
        assert check_admin_access(_make_request(user)) is True

    def test_user_missing_is_authenticated_attribute_defaults_false(self):
        """User with no is_authenticated attribute defaults to False → access denied."""
        user = MagicMock(spec=["is_staff", "is_superuser"])
        user.is_staff = True
        user.is_superuser = True
        assert check_admin_access(_make_request(user)) is False

    def test_user_missing_is_staff_and_superuser_defaults_false(self):
        """Authenticated user with no is_staff / is_superuser → both default False → denied."""
        user = MagicMock(spec=["is_authenticated"])
        user.is_authenticated = True
        assert check_admin_access(_make_request(user)) is False


# ---------------------------------------------------------------------------
# check_model_permission
# ---------------------------------------------------------------------------


class TestCheckModelPermission:
    def setup_method(self):
        self.model_class = MagicMock()

    def test_request_has_no_user_attribute(self):
        assert check_model_permission(object(), self.model_class, "view") is False

    def test_user_is_none(self):
        assert check_model_permission(_make_request(None), self.model_class, "view") is False

    def test_superuser_has_all_permissions(self):
        request = _make_request(_superuser())
        for action in ("view", "add", "change", "delete"):
            assert check_model_permission(request, self.model_class, action) is True

    def test_staff_has_all_permissions(self):
        request = _make_request(_staff_user())
        for action in ("view", "add", "change", "delete"):
            assert check_model_permission(request, self.model_class, action) is True

    def test_plain_user_with_has_perm_returns_true(self):
        """Non-staff/superuser user that possesses has_perm attribute returns True."""
        request = _make_request(_plain_user(has_has_perm=True))
        assert check_model_permission(request, self.model_class, "view") is True

    def test_plain_user_without_has_perm_returns_false(self):
        """Non-staff/superuser user lacking has_perm attribute returns False."""
        request = _make_request(_plain_user(has_has_perm=False))
        assert check_model_permission(request, self.model_class, "view") is False

    def test_superuser_short_circuits_before_staff_check(self):
        """is_superuser=True returns True even when is_staff=False."""
        user = MagicMock(spec=["is_authenticated", "is_staff", "is_superuser"])
        user.is_superuser = True
        user.is_staff = False
        request = _make_request(user)
        assert check_model_permission(request, self.model_class, "add") is True


# ---------------------------------------------------------------------------
# check_object_permission
# ---------------------------------------------------------------------------


class TestCheckObjectPermission:
    def setup_method(self):
        self.obj = MagicMock()

    def test_request_has_no_user_attribute(self):
        assert check_object_permission(object(), self.obj, "change") is False

    def test_user_is_none(self):
        assert check_object_permission(_make_request(None), self.obj, "change") is False

    def test_superuser_has_object_permission(self):
        request = _make_request(_superuser())
        assert check_object_permission(request, self.obj, "change") is True

    def test_superuser_has_delete_permission(self):
        request = _make_request(_superuser())
        assert check_object_permission(request, self.obj, "delete") is True

    def test_staff_user_delegates_to_model_permission(self):
        """check_object_permission falls through to check_model_permission for staff."""
        request = _make_request(_staff_user())
        assert check_object_permission(request, self.obj, "delete") is True

    def test_plain_user_with_has_perm_returns_true(self):
        request = _make_request(_plain_user(has_has_perm=True))
        assert check_object_permission(request, self.obj, "view") is True

    def test_plain_user_without_has_perm_returns_false(self):
        request = _make_request(_plain_user(has_has_perm=False))
        assert check_object_permission(request, self.obj, "view") is False

    def test_superuser_short_circuits_before_model_check(self):
        """Superuser never reaches check_model_permission — still returns True."""
        user = MagicMock(spec=["is_superuser"])
        user.is_superuser = True
        request = _make_request(user)
        assert check_object_permission(request, self.obj, "change") is True


# ---------------------------------------------------------------------------
# PermissionChecker — construction
# ---------------------------------------------------------------------------


class TestPermissionCheckerConstruction:
    def test_stores_request(self):
        request = _make_request(_staff_user())
        checker = PermissionChecker(request)
        assert checker.request is request

    def test_stores_user_from_request(self):
        user = _staff_user()
        checker = PermissionChecker(_make_request(user))
        assert checker.user is user

    def test_user_defaults_to_none_when_request_has_no_user(self):
        request = object()
        checker = PermissionChecker(request)
        assert checker.user is None


# ---------------------------------------------------------------------------
# PermissionChecker — is_authenticated
# ---------------------------------------------------------------------------


class TestPermissionCheckerIsAuthenticated:
    def test_user_none(self):
        checker = PermissionChecker(_make_request(None))
        assert checker.is_authenticated is False

    def test_no_user_attribute_on_request(self):
        checker = PermissionChecker(object())
        assert checker.is_authenticated is False

    def test_user_authenticated_true(self):
        user = MagicMock()
        user.is_authenticated = True
        assert PermissionChecker(_make_request(user)).is_authenticated is True

    def test_user_authenticated_false(self):
        user = MagicMock()
        user.is_authenticated = False
        assert PermissionChecker(_make_request(user)).is_authenticated is False

    def test_user_missing_is_authenticated_attribute(self):
        user = MagicMock(spec=[])
        assert PermissionChecker(_make_request(user)).is_authenticated is False


# ---------------------------------------------------------------------------
# PermissionChecker — is_staff
# ---------------------------------------------------------------------------


class TestPermissionCheckerIsStaff:
    def test_user_none(self):
        assert PermissionChecker(_make_request(None)).is_staff is False

    def test_no_user_attribute_on_request(self):
        assert PermissionChecker(object()).is_staff is False

    def test_user_is_staff_true(self):
        user = MagicMock()
        user.is_staff = True
        assert PermissionChecker(_make_request(user)).is_staff is True

    def test_user_is_staff_false(self):
        user = MagicMock()
        user.is_staff = False
        assert PermissionChecker(_make_request(user)).is_staff is False

    def test_user_missing_is_staff_attribute(self):
        user = MagicMock(spec=[])
        assert PermissionChecker(_make_request(user)).is_staff is False


# ---------------------------------------------------------------------------
# PermissionChecker — is_superuser
# ---------------------------------------------------------------------------


class TestPermissionCheckerIsSuperuser:
    def test_user_none(self):
        assert PermissionChecker(_make_request(None)).is_superuser is False

    def test_no_user_attribute_on_request(self):
        assert PermissionChecker(object()).is_superuser is False

    def test_user_is_superuser_true(self):
        user = MagicMock()
        user.is_superuser = True
        assert PermissionChecker(_make_request(user)).is_superuser is True

    def test_user_is_superuser_false(self):
        user = MagicMock()
        user.is_superuser = False
        assert PermissionChecker(_make_request(user)).is_superuser is False

    def test_user_missing_is_superuser_attribute(self):
        user = MagicMock(spec=[])
        assert PermissionChecker(_make_request(user)).is_superuser is False


# ---------------------------------------------------------------------------
# PermissionChecker — has_admin_access
# ---------------------------------------------------------------------------


class TestPermissionCheckerHasAdminAccess:
    def test_not_authenticated(self):
        user = MagicMock()
        user.is_authenticated = False
        user.is_staff = True
        user.is_superuser = False
        assert PermissionChecker(_make_request(user)).has_admin_access is False

    def test_authenticated_staff(self):
        assert PermissionChecker(_make_request(_staff_user())).has_admin_access is True

    def test_authenticated_superuser(self):
        assert PermissionChecker(_make_request(_superuser())).has_admin_access is True

    def test_authenticated_neither_staff_nor_superuser(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_staff = False
        user.is_superuser = False
        assert PermissionChecker(_make_request(user)).has_admin_access is False

    def test_unauthenticated_and_not_staff(self):
        checker = PermissionChecker(_make_request(None))
        assert checker.has_admin_access is False


# ---------------------------------------------------------------------------
# PermissionChecker — can_view / can_add
# ---------------------------------------------------------------------------


class TestPermissionCheckerCanViewAdd:
    def test_can_view_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_view(MagicMock()) is True

    def test_can_view_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_view(MagicMock()) is False

    def test_can_add_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_add(MagicMock()) is True

    def test_can_add_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_add(MagicMock()) is False

    def test_can_view_superuser(self):
        checker = PermissionChecker(_make_request(_superuser()))
        assert checker.can_view(MagicMock()) is True

    def test_can_add_superuser(self):
        checker = PermissionChecker(_make_request(_superuser()))
        assert checker.can_add(MagicMock()) is True


# ---------------------------------------------------------------------------
# PermissionChecker — can_change
# ---------------------------------------------------------------------------


class TestPermissionCheckerCanChange:
    def test_model_level_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_change(MagicMock()) is True

    def test_model_level_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_change(MagicMock()) is False

    def test_object_level_superuser(self):
        checker = PermissionChecker(_make_request(_superuser()))
        assert checker.can_change(MagicMock(), obj=MagicMock()) is True

    def test_object_level_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_change(MagicMock(), obj=MagicMock()) is True

    def test_object_level_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_change(MagicMock(), obj=MagicMock()) is False

    def test_obj_none_uses_model_level(self):
        """Explicitly passing obj=None should use model-level check."""
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_change(MagicMock(), obj=None) is True


# ---------------------------------------------------------------------------
# PermissionChecker — can_delete
# ---------------------------------------------------------------------------


class TestPermissionCheckerCanDelete:
    def test_model_level_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_delete(MagicMock()) is True

    def test_model_level_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_delete(MagicMock()) is False

    def test_object_level_superuser(self):
        checker = PermissionChecker(_make_request(_superuser()))
        assert checker.can_delete(MagicMock(), obj=MagicMock()) is True

    def test_object_level_staff(self):
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_delete(MagicMock(), obj=MagicMock()) is True

    def test_object_level_no_permission(self):
        checker = PermissionChecker(_make_request(_plain_user(has_has_perm=False)))
        assert checker.can_delete(MagicMock(), obj=MagicMock()) is False

    def test_obj_none_uses_model_level(self):
        """Explicitly passing obj=None should use model-level check."""
        checker = PermissionChecker(_make_request(_staff_user()))
        assert checker.can_delete(MagicMock(), obj=None) is True
