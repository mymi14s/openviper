"""Admin registration for the cart app."""

from __future__ import annotations

from openviper.admin import ChildTable, register
from openviper.admin.options import ModelAdmin

from .models import Cart, CartItem


class CartItemInline(ChildTable):
    model = CartItem
    fields = ["product", "quantity"]


@register(Cart)
class CartAdmin(ModelAdmin):
    list_display = ["id", "user", "created_at"]
    list_filter = ["created_at"]
    child_tables = [CartItemInline]


@register(CartItem)
class CartItemAdmin(ModelAdmin):
    list_display = ["id", "cart", "product", "quantity"]
    list_filter = ["cart"]
