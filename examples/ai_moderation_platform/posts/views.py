"""Views for the posts app."""

from __future__ import annotations

import logging

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import Comment, Post
from .serializers import (
    CommentCreateSerializer,
    CommentResponseSerializer,
    PostCreateSerializer,
    PostResponseSerializer,
)

logger = logging.getLogger(__name__)


def _serialize_post(p: Post, preview: bool = False) -> dict:
    data = PostResponseSerializer.from_orm(p).serialize()
    if preview and len(data["content"]) > 300:
        data["content"] = data["content"][:300] + "..."
    return data


class PostListCreateView(View):
    """View for listing and creating posts."""

    async def get(self, request: Request) -> Response:
        """List all visible posts."""
        posts = [p async for p in Post.objects.filter(is_hidden=False)]
        return JSONResponse({"posts": [_serialize_post(p, preview=True) for p in posts]})

    async def post(self, request: Request) -> Response:
        """Create a new post and moderate it."""
        try:
            if not request.user:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

            data = await request.json()
            serializer = PostCreateSerializer.validate(data)

            post = Post(
                title=serializer.title,
                content=serializer.content,
                author_id=request.user.id,
            )
            await post.save()

            # Re-fetch after after_insert (moderation may have set is_hidden=True)
            post = await Post.objects.get_or_none(id=post.id)

            return JSONResponse(
                {"id": post.id, "title": post.title, "is_hidden": post.is_hidden},
                status_code=201,
            )
        except Exception as e:
            logger.exception("Error in PostListCreateView.post")
            return JSONResponse({"error": str(e)}, status_code=500)


class PostDetailView(View):
    """View for retrieving a single post."""

    async def get(self, request: Request, post_id: int) -> Response:
        """Get a post by ID."""
        post = await Post.objects.filter(id=post_id).first()
        if not post:
            return JSONResponse({"error": "Post not found"}, status_code=404)
        if post.is_hidden:
            return JSONResponse({"error": "Post removed by moderation"}, status_code=403)
        return JSONResponse(_serialize_post(post))


class CommentListCreateView(View):
    """View for listing and creating comments."""

    async def get(self, request: Request) -> Response:
        """List comments for a post."""
        post_id = request.query_params.get("post_id")
        if not post_id:
            return JSONResponse({"error": "post_id query param required"}, status_code=400)
        comments = [c async for c in Comment.objects.filter(post_id=int(post_id), is_hidden=False)]
        result = [CommentResponseSerializer.from_orm(c).serialize() for c in comments]
        return JSONResponse({"comments": result})

    async def post(self, request: Request) -> Response:
        """Create a new comment."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        data = await request.json()
        serializer = CommentCreateSerializer.validate(data)

        comment = Comment(
            post_id=serializer.post_id,
            content=serializer.content,
            author_id=request.user.id,
        )
        await comment.save()

        return JSONResponse({"id": comment.id, "content": comment.content}, status_code=201)
