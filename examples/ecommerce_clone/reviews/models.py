"""Review model."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import (
    DateTimeField,
    ForeignKey,
    IntegerField,
    TextField,
    UUIDField,
)


class Review(Model):
    """Product review by a user."""

    _app_name = "reviews"

    id = UUIDField(primary_key=True, auto=True)
    user = ForeignKey("users.models.User", on_delete="CASCADE")
    product = ForeignKey("products.models.Product", on_delete="CASCADE")
    rating = IntegerField()
    comment = TextField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "reviews_review"

    def __str__(self) -> str:
        return f"Review({self.product_id} by {self.user_id})"
