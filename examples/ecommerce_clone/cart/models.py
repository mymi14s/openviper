"""Cart and CartItem models."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import (
    DateTimeField,
    ForeignKey,
    IntegerField,
    UUIDField,
)


class Cart(Model):
    """Shopping cart for a user (one per user)."""

    _app_name = "cart"

    id = UUIDField(primary_key=True, auto=True)
    user = ForeignKey("users.models.User", on_delete="CASCADE", unique=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "cart_cart"

    def __str__(self) -> str:
        return f"Cart({self.id})"


class CartItem(Model):
    """Item inside a cart."""

    _app_name = "cart"

    id = UUIDField(primary_key=True, auto=True)
    cart = ForeignKey(Cart, on_delete="CASCADE")
    product = ForeignKey("products.models.Product", on_delete="CASCADE")
    quantity = IntegerField(default=1)

    class Meta:
        table_name = "cart_item"

    def __str__(self) -> str:
        return f"CartItem({self.product_id} x{self.quantity})"
