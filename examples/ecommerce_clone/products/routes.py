"""Product routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import CategoryListView, ProductDetailView, ProductListView

router = Router(prefix="/products")

router.add("", ProductListView.as_view(), methods=["GET"])
router.add("/categories", CategoryListView.as_view(), methods=["GET"])
router.add("/{product_id}", ProductDetailView.as_view(), methods=["GET"])
