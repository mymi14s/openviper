"""Admin registration for chat models."""

from __future__ import annotations

from openviper.admin import register
from openviper.admin.options import ModelAdmin

from .models import ChatCache, ProductSummary


@register(ChatCache)
class ChatCacheAdmin(ModelAdmin):
    list_display = ["id", "question", "created_at"]
    search_fields = ["question", "answer"]


@register(ProductSummary)
class ProductSummaryAdmin(ModelAdmin):
    list_display = ["id", "product_id", "created_at"]
    search_fields = ["product_id", "summary"]
    readonly_fields = ["id", "product_id", "created_at", "summary"]
