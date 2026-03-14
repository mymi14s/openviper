from openviper.admin.decorators import register
from openviper.admin.options import ChildTable, ModelAdmin
from openviper.auth.models import (
    ContentType,
    ContentTypePermission,
    Permission,
    Role,
    RolePermission,
    RoleProfile,
    RoleProfileDetail,
    User,
    UserRole,
)


class UserRoleInline(ChildTable):
    model = UserRole
    fields = ["role"]
    label = "Assigned Roles"


class RoleProfileDetailInline(ChildTable):
    model = RoleProfileDetail
    fields = ["role"]
    label = "Included Roles"


class RolePermissionInline(ChildTable):
    model = RolePermission
    fields = ["permission"]
    label = "Direct Permissions"


class ContentTypePermissionInline(ChildTable):
    model = ContentTypePermission
    fields = ["role", "can_create", "can_read", "can_update", "can_delete"]


@register(User)
class UserAdmin(ModelAdmin):
    list_display = ["username", "email", "full_name", "is_active", "is_staff", "is_superuser"]
    search_fields = ["username", "email", "first_name", "last_name"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    child_tables = [UserRoleInline]

    def get_sensitive_fields(self, request=None, obj=None):
        return super().get_sensitive_fields(request, obj) + ["password"]


@register(Role)
class RoleAdmin(ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name", "description"]


@register(RoleProfile)
class RoleProfileAdmin(ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name", "description"]
    child_tables = [RoleProfileDetailInline]


@register(ContentType)
class ContentTypeAdmin(ModelAdmin):
    list_display = ["app_label", "model"]
    search_fields = ["app_label", "model"]
    child_tables = [ContentTypePermissionInline]

    def has_add_permission(self, request=None):
        return

    def has_delete_permission(self, request=None, obj=None):
        return


@register(Permission)
class PermissionAdmin(ModelAdmin):
    list_display = ["codename", "name", "content_type"]
    search_fields = ["codename", "name", "content_type"]
