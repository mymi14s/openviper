"""Product and Category models."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import (
    CharField,
    DateTimeField,
    DecimalField,
    ForeignKey,
    ImageField,
    IntegerField,
    TextField,
    UUIDField,
)
from openviper.db.models import Index


class Category(Model):
    """Product category — id IS the category name."""

    _app_name = "products"

    id = CharField(max_length=255, primary_key=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "products_category"

    @property
    def name(self) -> str:
        return self.id or ""

    def __str__(self) -> str:
        return self.id or ""


class Product(Model):
    """Product listing."""

    _app_name = "products"

    id = UUIDField(primary_key=True, auto=True)
    name = CharField(max_length=255)
    description = TextField(null=True, blank=True)
    price = DecimalField(max_digits=10, decimal_places=2)
    stock = IntegerField(default=0)
    category = ForeignKey(Category, on_delete="SET NULL", null=True)
    image = ImageField(upload_to="products/", null=True, blank=True)
    image_url = CharField(max_length=500, null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "products_product"
        indexes = [
            Index(fields=["name", "id"], name="idx_product_name_id"),
        ]

    def __str__(self) -> str:
        return self.name or ""
