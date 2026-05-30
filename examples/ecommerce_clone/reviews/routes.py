"""Review routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import ProductReviewsView, ReviewCreateView

router = Router(prefix="/reviews")

router.add("", ReviewCreateView.as_view(), methods=["POST"])
router.add("/product/{product_id}", ProductReviewsView.as_view(), methods=["GET"])
