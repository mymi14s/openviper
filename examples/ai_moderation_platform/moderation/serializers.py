"""Moderation serializers."""

from __future__ import annotations

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
    moderator_id: int | None = None
    created_at: str
    reviewed_at: str | None = None


class ModerationActionSerializer(Serializer):
    """Serializer for moderation action (approve/reject)."""

    action: str
    reason: str | None = None


class BanUserSerializer(Serializer):
    """Serializer for banning a user."""

    reason: str
