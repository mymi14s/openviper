"""Miniapp admin registrations — Todo and User models."""

from models import Todo  # noqa: E402

from openviper.admin import ModelAdmin, register
from openviper.auth import get_user_model

User = get_user_model()


@register(User)
class UserAdmin(ModelAdmin):
    list_display = [
        "id",
        "username",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
    ]
    search_fields = ["username", "email"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    readonly_fields = ["created_at"]
    exclude = ["password"]
    ordering = ["-created_at"]


@register(Todo)
class TodoAdmin(ModelAdmin):
    list_display = ["id", "title", "done", "owner_id", "created_at"]
    list_filter = ["done"]
    search_fields = ["title"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]
