"""Order and OrderItem models."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import (
    CharField,
    DateTimeField,
    DecimalField,
    ForeignKey,
    IntegerField,
    TextField,
    UUIDField,
)

ORDER_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("processing", "Processing"),
    ("shipped", "Shipped"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
]


class Order(Model):
    """Customer order."""

    _app_name = "orders"

    id = UUIDField(primary_key=True, auto=True)
    user = ForeignKey("users.models.User", on_delete="CASCADE")
    total_price = DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_address = TextField()
    status = CharField(max_length=20, default="pending", choices=ORDER_STATUS_CHOICES)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "orders_order"

    def __str__(self) -> str:
        return f"Order({self.id})"


class OrderItem(Model):
    """Item within an order."""

    _app_name = "orders"

    id = UUIDField(primary_key=True, auto=True)
    order = ForeignKey(Order, on_delete="CASCADE")
    product = ForeignKey("products.models.Product", on_delete="CASCADE")
    quantity = IntegerField(default=1)
    price = DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        table_name = "orders_item"

    def __str__(self) -> str:
        return f"OrderItem({self.product_id} x{self.quantity})"
