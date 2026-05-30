"""Moderation log model."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    FloatField,
    ForeignKey,
    IntegerField,
    TextField,
)


class ModerationLog(Model):
    """Log of AI moderation decisions."""

    _app_name = "moderation"

    # Generic foreign key pattern
    content_type = CharField(max_length=50)  # "post" or "comment"
    object_id = IntegerField()  # ID of the post or comment

    # AI classification results
    classification = CharField(max_length=20)  # safe, spam, abusive, hate, sexual
    confidence = FloatField()  # 0.0 to 1.0
    reason = TextField()  # AI explanation

    # Moderation workflow
    reviewed = BooleanField(default=False)
    approved = BooleanField(default=False)
    moderator = ForeignKey("users.models.User", on_delete="SET NULL", null=True)

    created_at = DateTimeField(auto_now_add=True)
    reviewed_at = DateTimeField(null=True)

    class Meta:
        table_name = "moderation_log"

    def __str__(self) -> str:
        return f"{self.content_type}:{self.object_id} - {self.classification}"
