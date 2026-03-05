"""Views for the moderation app."""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, datetime

from posts.models import Comment, Post

from openviper.http import JSONResponse, Request, Response
from openviper.http.views import View

from .models import ModerationLog
from .serializers import (
    ModerationActionSerializer,
    ModerationLogResponseSerializer,
)

logger = logging.getLogger(__name__)


class ModerationLogListView(View):
    """View for listing moderation logs (moderator only)."""

    async def get(self, request: Request) -> Response:
        """List all moderation logs."""
        try:
            # Simple staff check
            if not request.user or not request.user.is_staff:
                return JSONResponse({"error": "Forbidden"}, status_code=403)

            logs = [log async for log in ModerationLog.objects.all().order_by("-created_at")]
            serialized = []
            for log in logs:
                serialized.append(
                    ModerationLogResponseSerializer(
                        id=log.id,
                        content_type=log.content_type,
                        object_id=log.object_id,
                        classification=log.classification,
                        confidence=log.confidence,
                        reason=log.reason,
                        reviewed=log.reviewed,
                        approved=log.approved,
                        moderator_id=log.moderator,
                        created_at=log.created_at.isoformat() if log.created_at else "",
                        reviewed_at=log.reviewed_at.isoformat() if log.reviewed_at else None,
                    ).serialize()
                )
            return JSONResponse({"logs": serialized})
        except Exception as e:
            logger.exception("Error in ModerationLogListView.get")
            return JSONResponse({"error": str(e)}, status_code=500)


class ModerationActionView(View):
    """View for taking moderation actions on a log entry."""

    async def post(self, request: Request, log_id: int) -> Response:
        """Approve or reject content based on a log entry."""
        try:
            if not request.user or not request.user.is_staff:
                return JSONResponse({"error": "Forbidden"}, status_code=403)

            log = await ModerationLog.objects.get_or_none(id=log_id)
            if not log:
                return JSONResponse({"error": "Log not found"}, status_code=404)

            data = await request.json()
            serializer = ModerationActionSerializer.validate(data)

            log.reviewed = True
            log.reviewed_at = datetime.now(UTC)
            log.moderator = request.user.id

            if serializer.action == "approve":
                log.approved = True
                # Unhide content
                if log.content_type == "post":
                    post = await Post.objects.get_or_none(id=log.object_id)
                    if post:
                        post.is_hidden = False
                        await post.save()
                elif log.content_type == "comment":
                    comment = await Comment.objects.get_or_none(id=log.object_id)
                    if comment:
                        comment.is_hidden = False
                        await comment.save()
            else:
                log.approved = False
                # Ensure content is hidden
                if log.content_type == "post":
                    post = await Post.objects.get_or_none(id=log.object_id)
                    if post:
                        post.is_hidden = True
                        await post.save()
                elif log.content_type == "comment":
                    comment = await Comment.objects.get_or_none(id=log.object_id)
                    if comment:
                        comment.is_hidden = True
                        await comment.save()

            await log.save()
            return JSONResponse({"message": f"Content {serializer.action}ed successfully"})
        except Exception as e:
            logger.exception("Error in ModerationActionView.post")
            return JSONResponse(
                {"error": str(e), "traceback": traceback.format_exc()}, status_code=500
            )
