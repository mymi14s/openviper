"""Views for the posts app."""

from __future__ import annotations

import logging

from openviper.http import JSONResponse, Request, Response
from openviper.http.response import HTMLResponse
from openviper.http.views import View

from .models import Comment, CommentLike, Post, PostLike
from .serializers import (
    CommentCreateSerializer,
    CommentResponseSerializer,
    PostCreateSerializer,
    PostResponseSerializer,
    ReplyCreateSerializer,
    UpdateCommentSerializer,
)

logger = logging.getLogger(__name__)


def _serialize_post(p: Post, preview: bool = False, user_id: int | None = None) -> dict:
    data = PostResponseSerializer.from_orm(p).serialize()
    if preview and len(data["content"]) > 300:
        data["content"] = data["content"][:300] + "..."

    # Add user_liked field
    if user_id is not None:
        data["user_liked"] = hasattr(p, "_user_liked") and p._user_liked
    else:
        data["user_liked"] = False

    return data


class PostListCreateView(View):
    """View for listing and creating posts."""

    async def get(self, request: Request) -> Response:
        """List all visible posts with pagination and search."""
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 25))
        search_query = request.query_params.get("search", "").strip()

        # Build base queryset
        qs = Post.objects.filter(is_hidden=False)

        # Apply search filter (title or content)
        if search_query:
            # Fetch all non-hidden posts and filter in Python for OR search
            all_posts = []
            async for post in qs:
                if (
                    search_query.lower() in post.title.lower()
                    or search_query.lower() in post.content.lower()
                ):
                    all_posts.append(post)

            # Get total count
            total = len(all_posts)

            # Apply pagination manually
            offset = (page - 1) * page_size
            posts = all_posts[offset : offset + page_size]
        else:
            # Get total count before pagination
            total = await qs.count()

            # Calculate pagination
            offset = (page - 1) * page_size

            # Apply pagination
            posts = [p async for p in qs.offset(offset).limit(page_size)]

        total_pages = (total + page_size - 1) // page_size

        # Check user likes for serialization
        user_id = request.user.id if request.user else None
        user_likes = set()
        if user_id:
            user_likes = {like.post_id async for like in PostLike.objects.filter(user_id=user_id)}

        # Serialize posts with user_liked flag
        serialized_posts = []
        for post in posts:
            post._user_liked = post.id in user_likes
            serialized_posts.append(_serialize_post(post, preview=True, user_id=user_id))

        return JSONResponse(
            {
                "posts": serialized_posts,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
        )

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

        # Get comments count
        post.comments_count = await Comment.objects.filter(
            post_id=post_id,
            parent_comment_id=None,
            is_hidden=False,  # Top-level only
        ).count()

        # Check if user liked this post
        user_id = request.user.id if request.user else None
        if user_id:
            user_like = await PostLike.objects.filter(post_id=post_id, user_id=user_id).first()
            post._user_liked = user_like is not None
        else:
            post._user_liked = False

        return JSONResponse(_serialize_post(post, user_id=user_id))


class CommentListCreateView(View):
    """View for listing and creating comments."""

    async def get(self, request: Request) -> Response:
        """List top-level comments for a post with pagination."""
        post_id = request.query_params.get("post_id")
        if not post_id:
            return JSONResponse({"error": "post_id query param required"}, status_code=400)

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        # Fetch top-level comments only (parent_comment IS NULL) and not hidden
        total = await Comment.objects.filter(
            post_id=int(post_id),
            parent_comment_id=None,
            is_hidden=False,  # Top-level only
        ).count()

        offset = (page - 1) * page_size
        comments = [
            c
            async for c in Comment.objects.filter(
                post_id=int(post_id), parent_comment_id=None, is_hidden=False
            )
            .offset(offset)
            .limit(page_size)
        ]

        # Get user likes if authenticated
        user_id = request.user.id if request.user else None
        user_liked_comments = set()
        if user_id:
            user_liked_comments = {
                like.comment_id async for like in CommentLike.objects.filter(user_id=user_id)
            }

        # Serialize comments
        result = []
        for c in comments:
            serialized = CommentResponseSerializer.from_orm(c).serialize()
            serialized["user_liked"] = c.id in user_liked_comments
            result.append(serialized)

        total_pages = (total + page_size - 1) // page_size

        return JSONResponse(
            {
                "comments": result,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
        )

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


class BlogListView(View):
    """Webview for listing blog posts with pagination and search."""

    async def get(self, request: Request) -> Response:
        """Render index page with paginated posts and search."""
        # Get pagination parameters
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 25))

        # Get search query
        search_query = request.query_params.get("search", "").strip()

        # Build base queryset with select_related for author
        qs = Post.objects.select_related("author").filter(is_hidden=False)

        # Apply search filter (title or content)
        if search_query:
            # Fetch all non-hidden posts and filter in Python for OR search
            all_posts = []
            async for post in qs:
                if (
                    search_query.lower() in post.title.lower()
                    or search_query.lower() in post.content.lower()
                ):
                    all_posts.append(post)

            # Get total count
            total = len(all_posts)

            # Apply pagination manually
            offset = (page - 1) * page_size
            posts = all_posts[offset : offset + page_size]
        else:
            # Get total count before pagination
            total = await qs.count()

            # Calculate pagination
            offset = (page - 1) * page_size

            # Apply pagination
            posts = [p async for p in qs.offset(offset).limit(page_size)]

        total_pages = (total + page_size - 1) // page_size

        return HTMLResponse(
            template="posts/blog_list.html",
            context={
                "posts": posts,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "search_query": search_query,
            },
        )


class BlogListAPIView(View):
    """JSON API view for listing blog posts with pagination and search."""

    async def get(self, request: Request) -> Response:
        """Return paginated posts as JSON."""
        # Get pagination parameters
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 25))

        # Get search query
        search_query = request.query_params.get("search", "").strip()

        # Build base queryset
        qs = Post.objects.filter(is_hidden=False)

        # Apply search filter (title or content)
        if search_query:
            # Fetch all non-hidden posts and filter in Python for OR search
            all_posts = []
            async for post in qs:
                if (
                    search_query.lower() in post.title.lower()
                    or search_query.lower() in post.content.lower()
                ):
                    all_posts.append(post)

            # Get total count and apply pagination
            total = len(all_posts)
            offset = (page - 1) * page_size
            posts = all_posts[offset : offset + page_size]
        else:
            # Get total count before pagination
            total = await qs.count()

            # Apply pagination
            offset = (page - 1) * page_size
            posts = [p async for p in qs.offset(offset).limit(page_size)]

        # Serialize the posts
        results = [PostResponseSerializer.from_orm(p).serialize() for p in posts]

        # Build pagination URLs
        base_url = "/posts/blog/"
        next_url = None
        previous_url = None

        if page * page_size < total:
            next_url = f"{base_url}?page={page + 1}&page_size={page_size}"
            if search_query:
                next_url += f"&search={search_query}"

        if page > 1:
            previous_url = f"{base_url}?page={page - 1}&page_size={page_size}"
            if search_query:
                previous_url += f"&search={search_query}"

        return JSONResponse(
            {
                "count": total,
                "next": next_url,
                "previous": previous_url,
                "results": results,
            }
        )


class PostLikeToggleView(View):
    """View for toggling post likes."""

    async def post(self, request: Request, post_id: int) -> Response:
        """Toggle like for a post."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        post = await Post.objects.get_or_none(id=post_id)
        if not post:
            return JSONResponse({"error": "Post not found"}, status_code=404)

        try:
            # Check if user already liked this post
            existing_like = await PostLike.objects.filter(
                post_id=post_id, user_id=request.user.id
            ).first()

            if existing_like:
                # Unlike: delete the like record
                await existing_like.delete()
                liked = False
            else:
                # Like: create a like record
                like = PostLike(post_id=post_id, user_id=request.user.id)
                await like.save()
                liked = True

            # Update and return likes count
            likes_count = await PostLike.objects.filter(post_id=post_id).count()

            return JSONResponse({"liked": liked, "likes_count": likes_count}, status_code=200)
        except Exception as e:
            logger.exception("Error in PostLikeToggleView.post")
            return JSONResponse({"error": str(e)}, status_code=500)


class CommentLikeToggleView(View):
    """View for toggling comment likes."""

    async def post(self, request: Request, comment_id: int) -> Response:
        """Toggle like for a comment."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        comment = await Comment.objects.get_or_none(id=comment_id)
        if not comment:
            return JSONResponse({"error": "Comment not found"}, status_code=404)

        try:
            # Check if user already liked this comment
            existing_like = await CommentLike.objects.filter(
                comment_id=comment_id, user_id=request.user.id
            ).first()

            if existing_like:
                # Unlike: delete the like record
                await existing_like.delete()
                liked = False
            else:
                # Like: create a like record
                like = CommentLike(comment_id=comment_id, user_id=request.user.id)
                await like.save()
                liked = True

            # Update and return likes count
            likes_count = await CommentLike.objects.filter(comment_id=comment_id).count()

            return JSONResponse({"liked": liked, "likes_count": likes_count}, status_code=200)
        except Exception as e:
            logger.exception("Error in CommentLikeToggleView.post")
            return JSONResponse({"error": str(e)}, status_code=500)


class CommentDetailView(View):
    """View for retrieving, updating, and deleting individual comments."""

    async def get(self, request: Request, comment_id: int) -> Response:
        """Get a single comment by ID."""
        comment = await Comment.objects.get_or_none(id=comment_id)
        if not comment:
            return JSONResponse({"error": "Comment not found"}, status_code=404)
        if comment.is_hidden:
            return JSONResponse({"error": "Comment has been removed"}, status_code=403)

        # Check if user liked this comment
        user_id = request.user.id if request.user else None
        user_liked = False
        if user_id:
            user_like = await CommentLike.objects.filter(
                comment_id=comment_id, user_id=user_id
            ).first()
            user_liked = user_like is not None

        result = CommentResponseSerializer.from_orm(comment).serialize()
        result["user_liked"] = user_liked
        return JSONResponse(result)

    async def patch(self, request: Request, comment_id: int) -> Response:
        """Update a comment (owner only)."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        comment = await Comment.objects.get_or_none(id=comment_id)
        if not comment:
            return JSONResponse({"error": "Comment not found"}, status_code=404)

        # Ownership check
        if comment.author_id != request.user.id:
            return JSONResponse({"error": "Permission denied"}, status_code=403)

        try:
            data = await request.json()
            serializer = UpdateCommentSerializer.validate(data)

            if serializer.content is not None:
                comment.content = serializer.content
                await comment.save()

            result = CommentResponseSerializer.from_orm(comment).serialize()
            return JSONResponse(result, status_code=200)
        except Exception as e:
            logger.exception("Error in CommentDetailView.patch")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def delete(self, request: Request, comment_id: int) -> Response:
        """Delete a comment (owner only)."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        comment = await Comment.objects.get_or_none(id=comment_id)
        if not comment:
            return JSONResponse({"error": "Comment not found"}, status_code=404)

        # Ownership check
        if comment.author_id != request.user.id:
            return JSONResponse({"error": "Permission denied"}, status_code=403)

        try:
            await comment.delete()
            return JSONResponse({}, status_code=204)
        except Exception as e:
            logger.exception("Error in CommentDetailView.delete")
            return JSONResponse({"error": str(e)}, status_code=500)


class ReplyListCreateView(View):
    """View for listing and creating replies to a comment."""

    async def get(self, request: Request, comment_id: int) -> Response:
        """List replies to a comment with pagination."""
        parent_comment = await Comment.objects.get_or_none(id=comment_id)
        if not parent_comment:
            return JSONResponse({"error": "Parent comment not found"}, status_code=404)

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        # Fetch replies (direct children only, not hidden)
        total = await Comment.objects.filter(parent_comment_id=comment_id, is_hidden=False).count()

        offset = (page - 1) * page_size
        replies = [
            r
            async for r in Comment.objects.filter(parent_comment_id=comment_id, is_hidden=False)
            .offset(offset)
            .limit(page_size)
        ]

        # Get user likes if authenticated
        user_id = request.user.id if request.user else None
        user_liked_comments = set()
        if user_id:
            user_liked_comments = {
                like.comment_id async for like in CommentLike.objects.filter(user_id=user_id)
            }

        # Serialize replies
        result = []
        for r in replies:
            serialized = CommentResponseSerializer.from_orm(r).serialize()
            serialized["user_liked"] = r.id in user_liked_comments
            result.append(serialized)

        total_pages = (total + page_size - 1) // page_size

        return JSONResponse(
            {
                "replies": result,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
        )

    async def post(self, request: Request, comment_id: int) -> Response:
        """Create a reply to a comment."""
        if not request.user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        # Verify parent comment exists
        parent_comment = await Comment.objects.get_or_none(id=comment_id)
        if not parent_comment:
            return JSONResponse({"error": "Parent comment not found"}, status_code=404)

        try:
            data = await request.json()
            serializer = ReplyCreateSerializer.validate(data)

            # Create reply with parent_comment_id
            reply = Comment(
                post_id=parent_comment.post_id,  # Inherit post_id from parent
                content=serializer.content,
                author_id=request.user.id,
                parent_comment_id=comment_id,
            )
            await reply.save()

            return JSONResponse(
                {"id": reply.id, "content": reply.content, "parent_comment_id": comment_id},
                status_code=201,
            )
        except Exception as e:
            logger.exception("Error in ReplyListCreateView.post")
            return JSONResponse({"error": str(e)}, status_code=500)


class BlogDetailView(View):
    """Webview for a single blog post."""

    async def get(self, request: Request, post_id: int) -> Response:
        """Render post detail page."""
        # Eagerly load post with author via select_related
        post = await Post.objects.select_related("author").filter(id=post_id).first()
        if not post or post.is_hidden:
            return Response("Post not found", status_code=404)

        # Eagerly load comments with authors to avoid N+1 queries in template
        comments = [
            c
            async for c in Comment.objects.select_related("author").filter(
                post_id=post.id,
                parent_comment_id=None,
                is_hidden=False,  # Top-level comments only
            )
        ]
        return HTMLResponse(
            template="posts/blog_detail.html", context={"post": post, "comments": comments}
        )
