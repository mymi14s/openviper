"""Post and comment serializers."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from openviper.serializers import Serializer


class PostCreateSerializer(Serializer):
    """Serializer for creating a post."""

    title: str
    content: str


class PostUpdateSerializer(Serializer):
    """Serializer for updating a post."""

    title: str | None = None
    content: str | None = None


class PostResponseSerializer(Serializer):
    """Serializer for post response."""

    id: int
    title: str
    content: str
    author_id: int = Field(validation_alias="author")
    author_username: str | None = None
    is_hidden: bool
    likes_count: int
    created_at: datetime
    updated_at: datetime
    moderation_status: str | None = None


class CommentCreateSerializer(Serializer):
    """Serializer for creating a comment."""

    post_id: int
    content: str


class CommentUpdateSerializer(Serializer):
    """Serializer for updating a comment."""

    content: str | None = None


class CommentResponseSerializer(Serializer):
    """Serializer for comment response."""

    id: int
    post_id: int = Field(validation_alias="post")
    content: str
    author_id: int = Field(validation_alias="author")
    author_username: str | None = None
    is_hidden: bool
    created_at: datetime
    updated_at: datetime


class PostLikeSerializer(Serializer):
    """Serializer for post like."""

    post_id: int


class PostReportSerializer(Serializer):
    """Serializer for reporting a post."""

    post_id: int
    reason: str
