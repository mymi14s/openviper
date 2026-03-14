"""Admin registration for the orders app."""

from __future__ import annotations

from openviper.admin import ActionResult, ChildTable, action, register
from openviper.admin.options import ModelAdmin

from .models import Order, OrderItem


class OrderItemInline(ChildTable):
    model = OrderItem
    fields = ["product", "quantity", "price"]


@register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["id", "user", "total_price", "status", "shipping_address", "created_at"]
    search_fields = ["shipping_address"]
    list_filter = ["status", "created_at"]
    actions = ["mark_shipped", "mark_delivered", "mark_cancelled"]
    child_tables = [OrderItemInline]

    @action(description="Mark selected orders as shipped")
    async def mark_shipped(self, queryset, request):
        count = await queryset.update(status="shipped")
        return ActionResult(success=True, count=count, message=f"Marked {count} orders as shipped.")

    @action(description="Mark selected orders as delivered")
    async def mark_delivered(self, queryset, request):
        count = await queryset.update(status="delivered")
        return ActionResult(success=True, count=count, message=f"Marked {count} orders as delivered.")

    @action(description="Cancel selected orders")
    async def mark_cancelled(self, queryset, request):
        count = await queryset.update(status="cancelled")
        return ActionResult(success=True, count=count, message=f"Cancelled {count} orders.")


@register(OrderItem)
class OrderItemAdmin(ModelAdmin):
    list_display = ["id", "order", "product", "quantity", "price"]
    list_filter = ["order"]
