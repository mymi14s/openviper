"""Post and Comment models."""

from __future__ import annotations

import logging
import os
from typing import Any

from openviper.auth import get_user_model
from openviper.db import Model
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    TextField,
)

User = get_user_model()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Avoid adding multiple handlers if re-imported
if not any(
    isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("posts.log")
    for h in logger.handlers
):
    _log_file = os.path.join(os.getcwd(), "posts.log")
    _fh = logging.FileHandler(_log_file)
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)


class Post(Model):
    """Blog post/content model."""

    _app_name = "posts"

    title = CharField(max_length=255)
    content = TextField()
    author = ForeignKey(User, on_delete="CASCADE")
    is_hidden = BooleanField(default=False, null=True, blank=True)
    likes_count = IntegerField(default=0, null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "posts_post"

    def __str__(self) -> str:
        return self.title or ""

    async def after_insert(self) -> None:
        """Enqueue AI moderation after a post is saved."""
        from posts.tasks import moderate

        moderate.send(self.id)

    async def on_update(self) -> None:
        """On update hook."""

    async def on_change(self, previous_state: dict[str, Any]) -> None:
        """On change hook."""


class Comment(Model):
    """Comment on a post."""

    _app_name = "posts"

    post = ForeignKey("posts.models.Post", on_delete="CASCADE")
    content = TextField()
    author = ForeignKey(User, on_delete="CASCADE")
    is_hidden = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "posts_comment"

    def __str__(self) -> str:
        return f"Comment {self.id} on post:{self.post_id}"


class PostLike(Model):
    """Track post likes."""

    _app_name = "posts"

    post = ForeignKey("posts.models.Post", on_delete="CASCADE")
    user = ForeignKey(User, on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "posts_like"


class PostReport(Model):
    """User reports on posts."""

    _app_name = "posts"

    post = ForeignKey(Post, on_delete="CASCADE")
    reported_by = ForeignKey(User, on_delete="CASCADE")
    reason = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "posts_report"
