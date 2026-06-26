"""Unit tests for notification model."""

from __future__ import annotations

import pytest

from agents.models import Agent
from notifications.models import Notification
from tweets.models import Tweet


@pytest.fixture
async def setup_data():
    a1 = Agent(username="notified", email="n1@test.com", is_human=True)
    await a1.set_password("password123")
    await a1.save()
    a2 = Agent(username="notifier", email="n2@test.com", is_human=True)
    await a2.set_password("password123")
    await a2.save()
    tweet = await Tweet.objects.create(author_id=a1.id, content="My tweet")
    return a1, a2, tweet


class TestNotification:
    """Test Notification model."""

    @pytest.mark.asyncio
    async def test_create_notification(self, setup_data: tuple[Agent, Agent, Tweet]) -> None:
        a1, a2, tweet = setup_data
        notification = await Notification.objects.create(
            recipient_id=a1.id,
            actor_id=a2.id,
            type="like",
            tweet_id=tweet.id,
        )
        assert notification.id is not None
        assert notification.type == "like"
        assert notification.read_at is None

    @pytest.mark.asyncio
    async def test_notification_str(self, setup_data: tuple[Agent, Agent, Tweet]) -> None:
        a1, a2, tweet = setup_data
        notification = await Notification.objects.create(
            recipient_id=a1.id,
            actor_id=a2.id,
            type="retweet",
            tweet_id=tweet.id,
        )
        assert "retweet" in str(notification)
