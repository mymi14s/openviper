"""Admin registration for the reviews app."""

from __future__ import annotations

from openviper.admin import register
from openviper.admin.options import ModelAdmin

from .models import Review


@register(Review)
class ReviewAdmin(ModelAdmin):
    list_display = ["id", "user", "product", "rating", "created_at"]
    search_fields = ["comment"]
    list_filter = ["rating", "created_at"]
