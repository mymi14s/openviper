"""User routes."""

from __future__ import annotations

from openviper.routing import Router

from .views import LoginView, MeView, RegisterView

router = Router(prefix="/auth")

router.add("/register", RegisterView.as_view(), methods=["POST"])
router.add("/login", LoginView.as_view(), methods=["POST"])
router.add("/me", MeView.as_view(), methods=["GET"])
