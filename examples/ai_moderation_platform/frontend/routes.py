"""Frontend routes - registers the SPA at /."""

from __future__ import annotations

from openviper.routing import Router

from .views import FrontendView

router = Router(prefix="")

router.add("", FrontendView.as_view(), methods=["GET"])
