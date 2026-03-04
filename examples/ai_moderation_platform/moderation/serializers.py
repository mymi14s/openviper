"""Moderation serializers."""

from __future__ import annotations

from typing import Any, Optional

from openviper.serializers import Serializer


class ModerationLogResponseSerializer(Serializer):
    """Serializer for moderation log response."""

    id: int
    content_type: str
    object_id: int
    classification: str
    confidence: float
    reason: str
    reviewed: bool
    approved: bool
    moderator_id: Optional[int] = None
    created_at: str
    reviewed_at: Optional[str] = None


class ModerationActionSerializer(Serializer):
    """Serializer for moderation action (approve/reject)."""

    action: str
    reason: Optional[str] = None


class BanUserSerializer(Serializer):
    """Serializer for banning a user."""

    reason: str
