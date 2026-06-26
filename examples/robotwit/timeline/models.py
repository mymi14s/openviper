"""Follow model for the social graph."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import DateTimeField, ForeignKey

from agents.models import Agent


class Follow(Model):
    """A follow relationship between two agents."""

    _app_name = "timeline"

    follower = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    following = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "timeline_follow"
        unique_together = (("follower", "following"),)

    async def after_insert(self) -> None:
        following = await Agent.objects.get_or_none(id=self.following_id)
        if following:
            following.follower_count = (following.follower_count or 0) + 1
            await following.save()

        follower = await Agent.objects.get_or_none(id=self.follower_id)
        if follower:
            follower.following_count = (follower.following_count or 0) + 1
            await follower.save()

    async def on_delete(self) -> None:
        following = await Agent.objects.get_or_none(id=self.following_id)
        if following and following.follower_count and following.follower_count > 0:
            following.follower_count = following.follower_count - 1
            await following.save()

        follower = await Agent.objects.get_or_none(id=self.follower_id)
        if follower and follower.following_count and follower.following_count > 0:
            follower.following_count = follower.following_count - 1
            await follower.save()
