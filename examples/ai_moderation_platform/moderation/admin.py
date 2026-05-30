"""Admin registration for the moderation app."""

from __future__ import annotations

from openviper.admin import ModelAdmin, register

from .models import ModerationLog


@register(ModerationLog)
class ModerationLogAdmin(ModelAdmin):
    list_display = [
        "id",
        "content_type",
        "object_id",
        "classification",
        "reviewed",
        "approved",
        "created_at",
    ]
    list_filter = ["classification", "reviewed", "approved", "created_at"]
    search_fields = ["reason"]
