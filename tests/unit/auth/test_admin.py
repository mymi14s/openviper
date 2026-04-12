"""Unit tests for openviper.auth.admin module."""

from openviper.auth.admin import (
    ContentTypeAdmin,
    ContentTypePermissionInline,
    PermissionAdmin,
    RoleAdmin,
    RolePermissionInline,
    RoleProfileAdmin,
    RoleProfileDetailInline,
    UserAdmin,
    UserRoleInline,
)
from openviper.auth.models import ContentType, User


class TestUserAdmin:
    """Tests for UserAdmin configuration."""

    def test_has_correct_list_display(self):
        """Should display important user fields in list view."""
        assert "username" in UserAdmin.list_display
        assert "email" in UserAdmin.list_display
        assert "is_active" in UserAdmin.list_display
        assert "is_staff" in UserAdmin.list_display
        assert "is_superuser" in UserAdmin.list_display

    def test_has_search_fields(self):
        """Should allow searching by username and email."""
        assert "username" in UserAdmin.search_fields
        assert "email" in UserAdmin.search_fields

    def test_has_list_filters(self):
        """Should allow filtering by status fields."""
        assert "is_active" in UserAdmin.list_filter
        assert "is_staff" in UserAdmin.list_filter
        assert "is_superuser" in UserAdmin.list_filter

    def test_password_is_sensitive_field(self):
        """Should mark password as sensitive field."""
        admin = UserAdmin(User)
        sensitive_fields = admin.get_sensitive_fields()
        assert "password" in sensitive_fields


class TestRoleAdmin:
    """Tests for RoleAdmin configuration."""

    def test_has_correct_list_display(self):
        """Should display name and description."""
        assert "name" in RoleAdmin.list_display
        assert "description" in RoleAdmin.list_display

    def test_has_search_fields(self):
        """Should allow searching by name and description."""
        assert "name" in RoleAdmin.search_fields
        assert "description" in RoleAdmin.search_fields


class TestRoleProfileAdmin:
    """Tests for RoleProfileAdmin configuration."""

    def test_has_correct_list_display(self):
        """Should display name and description."""
        assert "name" in RoleProfileAdmin.list_display
        assert "description" in RoleProfileAdmin.list_display

    def test_has_search_fields(self):
        """Should allow searching by name and description."""
        assert "name" in RoleProfileAdmin.search_fields


class TestContentTypeAdmin:
    """Tests for ContentTypeAdmin configuration."""

    def test_has_correct_list_display(self):
        """Should display app_label and model."""
        assert "app_label" in ContentTypeAdmin.list_display
        assert "model" in ContentTypeAdmin.list_display

    def test_has_search_fields(self):
        """Should allow searching by app_label and model."""
        assert "app_label" in ContentTypeAdmin.search_fields
        assert "model" in ContentTypeAdmin.search_fields

    def test_has_no_add_permission(self):
        """Should not allow manual creation of content types."""
        admin = ContentTypeAdmin(ContentType)
        assert not admin.has_add_permission()

    def test_has_no_delete_permission(self):
        """Should not allow manual deletion of content types."""
        admin = ContentTypeAdmin(ContentType)
        assert not admin.has_delete_permission()


class TestPermissionAdmin:
    """Tests for PermissionAdmin configuration."""

    def test_has_correct_list_display(self):
        """Should display codename, name, and content_type."""
        assert "codename" in PermissionAdmin.list_display
        assert "name" in PermissionAdmin.list_display
        assert "content_type" in PermissionAdmin.list_display

    def test_has_search_fields(self):
        """Should allow searching by all display fields."""
        assert "codename" in PermissionAdmin.search_fields
        assert "name" in PermissionAdmin.search_fields
        assert "content_type" in PermissionAdmin.search_fields


class TestInlineConfigurations:
    """Tests for inline table configurations."""

    def test_user_role_inline_configuration(self):
        """Should configure UserRole inline correctly."""
        assert UserRoleInline.label == "Assigned Roles"
        assert "role" in UserRoleInline.fields

    def test_role_profile_detail_inline_configuration(self):
        """Should configure RoleProfileDetail inline correctly."""
        assert RoleProfileDetailInline.label == "Included Roles"
        assert "role" in RoleProfileDetailInline.fields

    def test_role_permission_inline_configuration(self):
        """Should configure RolePermission inline correctly."""
        assert RolePermissionInline.label == "Direct Permissions"
        assert "permission" in RolePermissionInline.fields

    def test_content_type_permission_inline_configuration(self):
        """Should configure ContentTypePermission inline correctly."""
        assert "role" in ContentTypePermissionInline.fields
        assert "can_create" in ContentTypePermissionInline.fields
        assert "can_read" in ContentTypePermissionInline.fields
        assert "can_update" in ContentTypePermissionInline.fields
        assert "can_delete" in ContentTypePermissionInline.fields
