"""API routes for notifications."""

from __future__ import annotations

from agents.models import Agent

from notifications.models import Notification
from openviper.auth.decorators import login_required
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.routing import Router
from openviper.utils import timezone

router = Router()


@router.get("/notifications")
@login_required
async def list_notifications(request: Request) -> JSONResponse:
    """List notifications for the current user."""
    unread_only = request.query_params.get("unread", "false") == "true"
    limit = min(int(request.query_params.get("limit", "20")), 50)

    qs = Notification.objects.filter(recipient_id=request.user.id).order_by("-created_at")
    if unread_only:
        qs = qs.filter(read_at__isnull=True)

    notifications = await qs.limit(limit).all()
    results = []
    for n in notifications:
        actor = await Agent.objects.get_or_none(id=n.actor_id)
        results.append(
            {
                "id": n.id,
                "type": n.type,
                "actor": {
                    "id": actor.id if actor else None,
                    "username": actor.username if actor else None,
                    "display_name": actor.display_name if actor else None,
                    "avatar_url": actor.avatar_url if actor else None,
                }
                if actor
                else None,
                "tweet_id": n.tweet_id,
                "read_at": str(n.read_at) if n.read_at else None,
                "created_at": str(n.created_at) if n.created_at else None,
            }
        )
    return JSONResponse({"results": results})


@router.get("/notifications/unread-count")
@login_required
async def unread_count(request: Request) -> JSONResponse:
    """Get unread notification count."""
    count = await Notification.objects.filter(
        recipient_id=request.user.id,
        read_at__isnull=True,
    ).count()
    return JSONResponse({"count": count})


@router.post("/notifications/mark-read")
@login_required
async def mark_read(request: Request) -> JSONResponse:
    """Mark all notifications as read."""
    notifications = await Notification.objects.filter(
        recipient_id=request.user.id,
        read_at__isnull=True,
    ).all()

    for n in notifications:
        n.read_at = timezone.now()
        await n.save()

    return JSONResponse({"marked_read": len(notifications)})
