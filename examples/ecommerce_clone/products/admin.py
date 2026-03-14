"""Admin registration for the products app."""

from __future__ import annotations

from openviper.admin import register
from openviper.admin.options import ModelAdmin

from .models import Category, Product


@register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ["id", "created_at"]
    search_fields = ["id"]


@register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ["id", "name", "price", "stock", "category", "created_at"]
    search_fields = ["name", "description"]
    list_filter = ["category"]
