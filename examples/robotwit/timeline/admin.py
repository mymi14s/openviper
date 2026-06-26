"""Admin registration for timeline app."""

from __future__ import annotations

from openviper.admin import ModelAdmin, register
from timeline.models import Follow


@register(Follow)
class FollowAdmin(ModelAdmin):
    list_display = ["id", "follower", "following", "created_at"]
    list_filter = ["created_at"]
