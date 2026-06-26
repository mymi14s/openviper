"""Notification model for user notifications."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import CharField, DateTimeField, ForeignKey


class Notification(Model):
    """A notification sent to a user about an interaction."""

    _app_name = "notifications"

    recipient = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    actor = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    type = CharField(max_length=30)
    tweet = ForeignKey(
        "tweets.models.Tweet",
        null=True,
        blank=True,
        on_delete="CASCADE",
    )
    read_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        table_name = "notifications_notification"

    def __str__(self) -> str:
        return f"{self.type} for {self.recipient_id} by {self.actor_id}"
