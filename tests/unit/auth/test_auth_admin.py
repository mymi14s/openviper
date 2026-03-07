from __future__ import annotations

import importlib
import sys

import openviper.auth.admin as auth_admin_mod


def test_inline_classes_and_registrations():
    """The module defines admin classes for Role, RoleProfile, ContentType, Permission."""
    assert hasattr(auth_admin_mod, "RoleAdmin")
    assert hasattr(auth_admin_mod, "RoleProfileAdmin")
    assert hasattr(auth_admin_mod, "ContentTypeAdmin")
    assert hasattr(auth_admin_mod, "PermissionAdmin")


def test_content_type_admin_permission_methods():
    """ContentTypeAdmin.has_add_permission and has_delete_permission return None."""
    from openviper.auth.admin import ContentTypeAdmin
    from openviper.auth.models import ContentType

    ct_admin = ContentTypeAdmin(ContentType)
    assert ct_admin.has_add_permission() is None
    assert ct_admin.has_delete_permission() is None


def test_conditional_user_admin_block():
    """Cover UserAdmin registration logic when USER_MODEL is empty."""
    from openviper.admin.registry import admin
    from openviper.auth.models import User
    from openviper.conf import settings

    # Save state so we can restore after the test
    saved_registry = dict(admin._registry)
    original_module = sys.modules.get("openviper.auth.admin")
    original_user_model = settings.USER_MODEL

    # Clear registry so the @register decorators won't raise AlreadyRegistered
    admin._registry.clear()
    # Temporarily unset USER_MODEL so the conditional block fires
    object.__setattr__(settings, "USER_MODEL", "")
    sys.modules.pop("openviper.auth.admin", None)

    try:
        importlib.import_module("openviper.auth.admin")
        assert admin.is_registered(User)

        ua = admin._registry[User]
        fields = ua.get_sensitive_fields()
        assert "password" in fields
    finally:
        # Restore everything so subsequent tests are unaffected
        object.__setattr__(settings, "USER_MODEL", original_user_model)
        admin._registry.clear()
        admin._registry.update(saved_registry)
        if original_module is not None:
            sys.modules["openviper.auth.admin"] = original_module
        else:
            sys.modules.pop("openviper.auth.admin", None)
