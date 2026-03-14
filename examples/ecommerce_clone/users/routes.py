"""User routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import LoginView, ProfileView, RegisterView

router = Router(prefix="/auth")

router.add("/register", RegisterView.as_view(), methods=["POST"])
router.add("/login", LoginView.as_view(), methods=["POST"])
router.add("/profile", ProfileView.as_view(), methods=["GET"])
