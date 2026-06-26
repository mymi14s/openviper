"""Admin registration for agents app."""

from __future__ import annotations

from openviper.admin import ModelAdmin, register

from agents.models import Agent, AgentPersonality


@register(AgentPersonality)
class AgentPersonalityAdmin(ModelAdmin):
    list_display = ["id", "name", "model_id", "temperature"]
    list_filter = ["model_id"]
    search_fields = ["name", "system_prompt"]


@register(Agent)
class AgentAdmin(ModelAdmin):
    list_display = [
        "id",
        "username",
        "display_name",
        "is_autonomous",
        "is_human",
        "follower_count",
        "following_count",
        "last_active_at",
    ]
    list_filter = ["is_autonomous", "is_human", "is_active"]
    search_fields = ["username", "display_name", "bio"]
