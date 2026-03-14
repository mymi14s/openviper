"""Product serializers."""

from __future__ import annotations

from decimal import Decimal

from openviper.serializers import Serializer


class CategorySerializer(Serializer):
    id: str | None = None
    name: str
    created_at: str | None = None


class ProductSerializer(Serializer):
    id: str | None = None
    name: str
    description: str | None = None
    price: Decimal
    stock: int = 0
    category_id: str | None = None
    image: str | None = None
    created_at: str | None = None


class ProductCreateSerializer(Serializer):
    name: str
    description: str | None = None
    price: Decimal
    stock: int = 0
    category_id: str | None = None
