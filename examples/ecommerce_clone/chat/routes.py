"""Chat routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import ChatView

router = Router(prefix="/chat")

router.add("", ChatView.as_view(), methods=["POST"])
