from openviper.admin.auth_admin import (
    ChangeHistoryAdmin,
    register_auth_models,
)
from openviper.admin.history import ChangeHistory
from openviper.admin.registry import admin
from openviper.auth import get_user_model
from openviper.auth.models import Permission, Role, RolePermission, UserRole


def test_change_history_admin_permissions():
    admin_instance = ChangeHistoryAdmin(ChangeHistory)
    assert admin_instance.has_add_permission() is False
    assert admin_instance.has_change_permission() is False
    assert admin_instance.has_delete_permission() is False


def test_register_auth_models():
    # We clear the global registry or use a mock

    # Store original state if any, or just clear
    admin._registry.clear()

    # Call the registration
    register_auth_models()

    # Check that the models are registered

    assert admin.is_registered(get_user_model())
    assert admin.is_registered(Permission)
    assert admin.is_registered(Role)
    assert admin.is_registered(UserRole)
    assert admin.is_registered(RolePermission)
    assert admin.is_registered(ChangeHistory)

    # Call it again to trigger the suppression of AlreadyRegistered
    register_auth_models()

    # Still registered
    assert admin.is_registered(Permission)
