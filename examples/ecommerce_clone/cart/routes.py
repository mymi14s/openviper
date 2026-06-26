"""Cart routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import CartAddView, CartRemoveView, CartUpdateView, CartView

router = Router(prefix="/cart")

router.add("", CartView.as_view(), methods=["GET"])
router.add("/add", CartAddView.as_view(), methods=["POST"])
router.add("/update", CartUpdateView.as_view(), methods=["POST"])
router.add("/remove", CartRemoveView.as_view(), methods=["POST"])
