"""Blog webview routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import BlogDetailView, BlogListView

router = Router(prefix="")

router.add("/", BlogListView.as_view(), methods=["GET"])
router.add("/{post_id:int}", BlogDetailView.as_view(), methods=["GET"])
