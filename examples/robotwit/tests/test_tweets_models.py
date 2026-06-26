"""Unit tests for tweet models."""

from __future__ import annotations

import pytest
from agents.models import Agent
from tweets.models import Bookmark, Hashtag, Like, Tweet


@pytest.fixture
async def agent():
    a = Agent(username="tweetuser", email="tweet@test.com", is_human=True)
    await a.set_password("password123")
    await a.save()
    return a


class TestTweet:
    """Test Tweet model."""

    @pytest.mark.asyncio
    async def test_create_tweet(self, agent: Agent) -> None:
        tweet = await Tweet.objects.create(
            author_id=agent.id,
            content="Hello, robotwit!",
        )
        assert tweet.id is not None
        assert tweet.content == "Hello, robotwit!"
        assert tweet.like_count == 0
        assert tweet.is_deleted is False

    @pytest.mark.asyncio
    async def test_tweet_hashtag_parsing(self, agent: Agent) -> None:
        await Tweet.objects.create(
            author_id=agent.id,
            content="Loving #AI and #robotwit today!",
        )
        tag1 = await Hashtag.objects.get_or_none(name="ai")
        tag2 = await Hashtag.objects.get_or_none(name="robotwit")
        assert tag1 is not None
        assert tag2 is not None
        assert tag1.tweet_count == 1

    @pytest.mark.asyncio
    async def test_tweet_reply_increments_count(self, agent: Agent) -> None:
        parent = await Tweet.objects.create(
            author_id=agent.id,
            content="Original tweet",
        )
        reply = await Tweet.objects.create(
            author_id=agent.id,
            content="This is a reply",
            reply_to_id=parent.id,
        )
        parent_refreshed = await Tweet.objects.get_or_none(id=parent.id)
        assert parent_refreshed.reply_count == 1
        assert reply.thread_id_id == parent.id


class TestLike:
    """Test Like model."""

    @pytest.mark.asyncio
    async def test_like_increments_count(self, agent: Agent) -> None:
        tweet = await Tweet.objects.create(
            author_id=agent.id,
            content="Like me!",
        )
        await Like.objects.create(agent_id=agent.id, tweet_id=tweet.id)
        tweet_refreshed = await Tweet.objects.get_or_none(id=tweet.id)
        assert tweet_refreshed.like_count == 1

    @pytest.mark.asyncio
    async def test_unlike_decrements_count(self, agent: Agent) -> None:
        tweet = await Tweet.objects.create(
            author_id=agent.id,
            content="Like and unlike me!",
        )
        like = await Like.objects.create(agent_id=agent.id, tweet_id=tweet.id)
        await like.delete()
        tweet_refreshed = await Tweet.objects.get_or_none(id=tweet.id)
        assert tweet_refreshed.like_count == 0


class TestBookmark:
    """Test Bookmark model."""

    @pytest.mark.asyncio
    async def test_create_bookmark(self, agent: Agent) -> None:
        tweet = await Tweet.objects.create(
            author_id=agent.id,
            content="Bookmark me!",
        )
        bookmark = await Bookmark.objects.create(
            agent_id=agent.id,
            tweet_id=tweet.id,
        )
        assert bookmark.id is not None
