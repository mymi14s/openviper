"""Order routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import CheckoutView, OrderDetailView, OrderListView

router = Router(prefix="/orders")

router.add("/checkout", CheckoutView.as_view(), methods=["POST"])
router.add("", OrderListView.as_view(), methods=["GET"])
router.add("/{order_id}", OrderDetailView.as_view(), methods=["GET"])
