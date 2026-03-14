"""Routes for the posts app."""

from __future__ import annotations

from openviper.routing import Router

from .views import (
    CommentDetailView,
    CommentLikeToggleView,
    CommentListCreateView,
    PostDetailView,
    PostListCreateView,
    BlogListAPIView,
    PostLikeToggleView,
    ReplyListCreateView,
)

router = Router(prefix="")

# Post routes
router.add("", PostListCreateView.as_view(), methods=["GET", "POST"])
router.add("/{post_id:int}", PostDetailView.as_view(), methods=["GET"])
router.add("/{post_id:int}/like/", PostLikeToggleView.as_view(), methods=["POST"])
router.add("/blog/", BlogListAPIView.as_view(), methods=["GET"])

# Comment routes
router.add("/comments", CommentListCreateView.as_view(), methods=["GET", "POST"])
router.add("/comments/{comment_id:int}", CommentDetailView.as_view(), methods=["GET", "PATCH", "DELETE"])
router.add("/comments/{comment_id:int}/like/", CommentLikeToggleView.as_view(), methods=["POST"])
router.add("/comments/{comment_id:int}/replies", ReplyListCreateView.as_view(), methods=["GET", "POST"])
