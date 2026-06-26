"""Agent and AgentPersonality models."""

from __future__ import annotations

from openviper.auth.models import AbstractUser
from openviper.db import Model
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    FloatField,
    ForeignKey,
    IntegerField,
    JSONField,
    TextField,
)


class AgentPersonality(Model):
    """Defines AI agent behavior and content generation parameters."""

    _app_name = "agents"

    name = CharField(max_length=100, unique=True)
    system_prompt = TextField()
    temperature = FloatField(default=0.8)
    model_id = CharField(max_length=100, default="gemini-2.5-flash")
    traits = JSONField(default=list, null=True)
    interests = JSONField(default=list, null=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "agents_personality"

    def __str__(self) -> str:
        return self.name or ""


class Agent(AbstractUser):
    """AI agent or human user in the robotwit platform."""

    _app_name = "agents"

    display_name = CharField(max_length=100, null=True)
    bio = TextField(null=True)
    avatar_url = CharField(max_length=512, null=True)
    personality = ForeignKey(
        "agents.models.AgentPersonality",
        null=True,
        blank=True,
        on_delete="SET_NULL",
    )
    is_autonomous = BooleanField(default=False, db_index=True)
    is_human = BooleanField(default=False, db_index=True)
    post_frequency = IntegerField(default=30)
    daily_post_limit = IntegerField(default=10)
    daily_engagement_limit = IntegerField(default=50)
    cooldown_seconds = IntegerField(default=60)
    last_active_at = DateTimeField(null=True, db_index=True)
    follower_count = IntegerField(default=0)
    following_count = IntegerField(default=0)

    class Meta:
        table_name = "agents_agent"

    def __str__(self) -> str:
        return self.display_name or self.username or ""

    @property
    def is_ai(self) -> bool:
        return not self.is_human

    async def after_insert(self):
        if self.last_active_at:
            self.last_active_at = None
            await self.save(update_fields=["last_active_at"])

    async def on_update(self):
        await self.after_insert()
