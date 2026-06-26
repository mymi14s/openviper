"""Routes for the moderation app."""

from __future__ import annotations

from openviper.routing import Router

from .views import ModerationActionView, ModerationLogListView

router = Router(prefix="")

# Log routes
router.add("/logs", ModerationLogListView.as_view(), methods=["GET"])

# Action routes
router.add("/logs/{log_id}/action", ModerationActionView.as_view(), methods=["POST"])
