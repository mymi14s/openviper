"""Admin registration for the users app."""

from __future__ import annotations

from openviper.admin import register
from openviper.admin.options import ModelAdmin
from openviper.auth.admin import UserRoleInline

from .models import User


@register(User)
class UserAdmin(ModelAdmin):
    list_display = ["username", "email", "full_name", "is_active", "is_staff", "is_superuser"]
    search_fields = ["username", "email", "first_name", "last_name"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    child_tables = [UserRoleInline]

    def get_sensitive_fields(self, request=None, obj=None):
        return super().get_sensitive_fields(request, obj) + ["password"]
