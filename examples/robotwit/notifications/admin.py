"""Admin registration for notifications app."""

from __future__ import annotations

from openviper.admin import ModelAdmin, register

from notifications.models import Notification


@register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ["id", "recipient", "actor", "type", "read_at", "created_at"]
    list_filter = ["type", "read_at", "created_at"]
    search_fields = ["type"]
