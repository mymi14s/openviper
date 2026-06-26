"""Unit tests for agent and personality models."""

from __future__ import annotations

import pytest
from agents.models import Agent, AgentPersonality


class TestAgentPersonality:
    """Test AgentPersonality model."""

    @pytest.mark.asyncio
    async def test_create_personality(self) -> None:
        personality = await AgentPersonality.objects.create(
            name="Test Personality",
            system_prompt="You are a test agent.",
            temperature=0.5,
            model_id="gemini-2.5-flash",
            traits=["curious"],
            interests=["science"],
        )
        assert personality.id is not None
        assert personality.name == "Test Personality"
        assert personality.temperature == 0.5

    @pytest.mark.asyncio
    async def test_personality_str(self) -> None:
        personality = await AgentPersonality.objects.create(
            name="My Personality",
            system_prompt="Test",
        )
        assert str(personality) == "My Personality"


class TestAgent:
    """Test Agent model."""

    @pytest.mark.asyncio
    async def test_create_human_agent(self) -> None:
        agent = Agent(
            username="testuser",
            email="test@test.com",
            display_name="Test User",
            is_human=True,
        )
        await agent.set_password("testpassword123")
        await agent.save()
        assert agent.id is not None
        assert agent.is_human is True
        assert agent.is_ai is False
        assert agent.is_autonomous is False

    @pytest.mark.asyncio
    async def test_create_ai_agent(self) -> None:
        personality = await AgentPersonality.objects.create(
            name="AI Test",
            system_prompt="You are an AI.",
        )
        agent = Agent(
            username="ai_agent_001",
            email="ai001@robotwit.ai",
            display_name="AI Agent",
            is_autonomous=True,
            is_human=False,
            personality_id=personality.id,
            post_frequency=30,
        )
        await agent.save()
        assert agent.id is not None
        assert agent.is_ai is True
        assert agent.is_autonomous is True

    @pytest.mark.asyncio
    async def test_agent_password_hashing(self) -> None:
        agent = Agent(username="pwduser", email="pwd@test.com")
        await agent.set_password("mypassword")
        await agent.save()
        assert agent.password is not None
        assert agent.password != "mypassword"
        assert await agent.check_password("mypassword") is True
        assert await agent.check_password("wrongpassword") is False
