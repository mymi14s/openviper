"""Product serializers."""

from __future__ import annotations

from openviper.serializers import ModelSerializer

from .models import Category, Product


class ProductSerializer(ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "stock",
            "category_id",
            "image",
            "image_url",
            "created_at",
        ]


class CategorySerializer(ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "created_at"]
