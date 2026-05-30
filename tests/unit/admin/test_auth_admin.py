from unittest.mock import MagicMock, patch

from openviper.admin.auth_admin import (
    ChangeHistoryAdmin,
    PermissionAdmin,
    RoleAdmin,
    RolePermissionAdmin,
    UserAdmin,
    UserRoleAdmin,
    register_auth_models,
)
from openviper.admin.history import ChangeHistory
from openviper.admin.registry import admin
from openviper.auth.models import Permission, Role, RolePermission, UserRole


class TestUserAdmin:
    """Test UserAdmin configuration."""

    def test_list_display(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "username" in user_admin.list_display
            assert "email" in user_admin.list_display
            assert "is_active" in user_admin.list_display
            assert "is_staff" in user_admin.list_display
            assert "is_superuser" in user_admin.list_display

    def test_list_filter(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "is_active" in user_admin.list_filter
            assert "is_staff" in user_admin.list_filter
            assert "is_superuser" in user_admin.list_filter

    def test_search_fields(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "username" in user_admin.search_fields
            assert "email" in user_admin.search_fields

    def test_exclude_password(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "password" in user_admin.exclude

    def test_sensitive_fields(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "password" in user_admin.sensitive_fields

    def test_readonly_fields(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert "created_at" in user_admin.readonly_fields
            assert "updated_at" in user_admin.readonly_fields
            assert "last_login" in user_admin.readonly_fields

    def test_fieldsets_structure(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            user_admin = UserAdmin(mock_user_model)
            assert len(user_admin.fieldsets) == 4
            # Check account fieldset
            assert user_admin.fieldsets[0][0] == "Account"
            assert "username" in user_admin.fieldsets[0][1]["fields"]


class TestPermissionAdmin:
    """Test PermissionAdmin configuration."""

    def test_list_display(self):
        permission_admin = PermissionAdmin(Permission)
        assert "name" in permission_admin.list_display
        assert "codename" in permission_admin.list_display
        assert "description" in permission_admin.list_display

    def test_search_fields(self):
        permission_admin = PermissionAdmin(Permission)
        assert "name" in permission_admin.search_fields
        assert "codename" in permission_admin.search_fields


class TestRoleAdmin:
    """Test RoleAdmin configuration."""

    def test_list_display(self):
        role_admin = RoleAdmin(Role)
        assert "name" in role_admin.list_display
        assert "description" in role_admin.list_display

    def test_search_fields(self):
        role_admin = RoleAdmin(Role)
        assert "name" in role_admin.search_fields


class TestUserRoleAdmin:
    """Test UserRoleAdmin configuration."""

    def test_list_display(self):
        user_role_admin = UserRoleAdmin(UserRole)
        assert "user_id" in user_role_admin.list_display
        assert "role_id" in user_role_admin.list_display


class TestRolePermissionAdmin:
    """Test RolePermissionAdmin configuration."""

    def test_list_display(self):
        role_perm_admin = RolePermissionAdmin(RolePermission)
        assert "role_id" in role_perm_admin.list_display
        assert "permission_id" in role_perm_admin.list_display


class TestChangeHistoryAdmin:
    """Test ChangeHistoryAdmin configuration (read-only)."""

    def test_list_display(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert "model_name" in history_admin.list_display
        assert "object_id" in history_admin.list_display
        assert "action" in history_admin.list_display
        assert "changed_by_username" in history_admin.list_display
        assert "change_time" in history_admin.list_display

    def test_list_filter(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert "action" in history_admin.list_filter
        assert "model_name" in history_admin.list_filter

    def test_search_fields(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert "model_name" in history_admin.search_fields
        assert "object_repr" in history_admin.search_fields
        assert "changed_by_username" in history_admin.search_fields

    def test_readonly_fields_include_all(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        readonly = history_admin.readonly_fields
        assert "model_name" in readonly
        assert "object_id" in readonly
        assert "action" in readonly
        assert "changed_by_username" in readonly

    def test_has_add_permission_returns_false(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert history_admin.has_add_permission() is False

    def test_has_change_permission_returns_false(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert history_admin.has_change_permission() is False

    def test_has_delete_permission_returns_false(self):
        history_admin = ChangeHistoryAdmin(ChangeHistory)
        assert history_admin.has_delete_permission() is False


class TestRegisterAuthModels:
    """Test register_auth_models function."""

    def setup_method(self):
        """Clear registry before each test."""
        admin.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        admin.clear()

    def test_registers_user_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(mock_user_model)

    def test_registers_permission_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(Permission)

    def test_registers_role_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(Role)

    def test_registers_user_role_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(UserRole)

    def test_registers_role_permission_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(RolePermission)

    def test_registers_change_history_model(self):
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            register_auth_models()
            assert admin.is_registered(ChangeHistory)

    def test_handles_already_registered_gracefully(self):
        """Test that calling register_auth_models multiple times doesn't raise."""
        with patch("openviper.admin.auth_admin.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.__name__ = "User"
            mock_user_model._app_name = "auth"
            mock_user_model._fields = {}
            mock_get_user.return_value = mock_user_model

            # First registration
            register_auth_models()
            # Second registration should not raise
            register_auth_models()

            # All models should still be registered
            assert admin.is_registered(Permission)
            assert admin.is_registered(Role)
