"""Miniapp admin registrations - Todo model."""

from models import Todo

from openviper.admin import ModelAdmin, register


@register(Todo)
class TodoAdmin(ModelAdmin):
    list_display = ["id", "title", "done", "owner_id", "created_at"]
    list_filter = ["done"]
    search_fields = ["title"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]
