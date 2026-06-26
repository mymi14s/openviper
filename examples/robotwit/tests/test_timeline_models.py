"""Unit tests for follow model and timeline."""

from __future__ import annotations

import pytest
from agents.models import Agent
from timeline.models import Follow


@pytest.fixture
async def two_agents():
    a1 = Agent(username="follower1", email="f1@test.com", is_human=True)
    await a1.set_password("password123")
    await a1.save()
    a2 = Agent(username="following1", email="f2@test.com", is_human=True)
    await a2.set_password("password123")
    await a2.save()
    return a1, a2


class TestFollow:
    """Test Follow model."""

    @pytest.mark.asyncio
    async def test_create_follow(self, two_agents: tuple[Agent, Agent]) -> None:
        a1, a2 = two_agents
        follow = await Follow.objects.create(
            follower_id=a1.id,
            following_id=a2.id,
        )
        assert follow.id is not None

    @pytest.mark.asyncio
    async def test_follow_increments_counts(self, two_agents: tuple[Agent, Agent]) -> None:
        a1, a2 = two_agents
        await Follow.objects.create(follower_id=a1.id, following_id=a2.id)

        a1_refreshed = await Agent.objects.get_or_none(id=a1.id)
        a2_refreshed = await Agent.objects.get_or_none(id=a2.id)
        assert a1_refreshed.following_count == 1
        assert a2_refreshed.follower_count == 1

    @pytest.mark.asyncio
    async def test_unfollow_decrements_counts(self, two_agents: tuple[Agent, Agent]) -> None:
        a1, a2 = two_agents
        follow = await Follow.objects.create(follower_id=a1.id, following_id=a2.id)
        await follow.delete()

        a1_refreshed = await Agent.objects.get_or_none(id=a1.id)
        a2_refreshed = await Agent.objects.get_or_none(id=a2.id)
        assert a1_refreshed.following_count == 0
        assert a2_refreshed.follower_count == 0
