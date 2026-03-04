"""Routes for the posts app."""

from __future__ import annotations

from openviper.routing import Router

from .views import CommentListCreateView, PostDetailView, PostListCreateView

router = Router(prefix="")

# Post routes
router.add("", PostListCreateView.as_view(), methods=["GET", "POST"])
router.add("/{post_id:int}", PostDetailView.as_view(), methods=["GET"])

# Comment routes
router.add("/comments", CommentListCreateView.as_view(), methods=["GET", "POST"])
