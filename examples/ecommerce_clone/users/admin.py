"""Admin registration for the users app."""

from __future__ import annotations

from openviper.admin import register, unregister
from openviper.admin.options import ModelAdmin
from openviper.auth.admin import UserRoleInline
from openviper.auth.models import User as OpenviperUser

from .models import User

unregister(OpenviperUser)


@register(User)
class UserAdmin(ModelAdmin):
    list_display = ["id", "username", "email", "name", "is_active", "is_staff", "is_superuser"]
    search_fields = ["username", "email", "name"]
    list_filter = ["is_active", "is_staff", "is_superuser", "country"]
    child_tables = [UserRoleInline]

    def get_sensitive_fields(self, request=None, obj=None):
        return super().get_sensitive_fields(request, obj) + ["password"]
