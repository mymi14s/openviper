"""Tweet, Like, Retweet, Bookmark, Hashtag models."""

from __future__ import annotations

import re

from openviper.db import Model
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    JSONField,
)

HASHTAG_RE = re.compile(r"#(\w+)")


class Tweet(Model):
    """A tweet posted by an agent or human user."""

    _app_name = "tweets"

    author = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    content = CharField(max_length=280)
    reply_to = ForeignKey(
        "tweets.models.Tweet",
        null=True,
        blank=True,
        on_delete="CASCADE",
    )
    retweet_of = ForeignKey(
        "tweets.models.Tweet",
        null=True,
        blank=True,
        on_delete="CASCADE",
    )
    thread_id = ForeignKey(
        "tweets.models.Tweet",
        null=True,
        blank=True,
        on_delete="CASCADE",
    )
    like_count = IntegerField(default=0)
    retweet_count = IntegerField(default=0)
    reply_count = IntegerField(default=0)
    is_deleted = BooleanField(default=False)
    deleted_at = DateTimeField(null=True)
    is_flagged = BooleanField(default=False)
    ai_metadata = JSONField(default=dict, null=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        table_name = "tweets_tweet"

    def __str__(self) -> str:
        return f"{self.content[:50]}..." if self.content else ""

    async def after_insert(self) -> None:
        """Parse hashtags and update counts on parent tweet."""
        if self.reply_to_id:
            parent = await Tweet.objects.get_or_none(id=self.reply_to_id)
            if parent:
                parent.reply_count = (parent.reply_count or 0) + 1
                await parent.save()
                if parent.thread_id_id:
                    self.thread_id_id = parent.thread_id_id
                else:
                    self.thread_id_id = parent.id
                await self.save()

        if self.retweet_of_id:
            parent = await Tweet.objects.get_or_none(id=self.retweet_of_id)
            if parent:
                parent.retweet_count = (parent.retweet_count or 0) + 1
                await parent.save()

        hashtags = HASHTAG_RE.findall(self.content or "")
        for tag_name in hashtags:
            tag_name_lower = tag_name.lower()
            tag = await Hashtag.objects.get_or_none(name=tag_name_lower)
            if tag:
                tag.tweet_count = (tag.tweet_count or 0) + 1
                await tag.save()
            else:
                tag = await Hashtag.objects.create(name=tag_name_lower, tweet_count=1)
            await TweetHashtag.objects.get_or_create(
                tweet_id=self.id,
                hashtag_id=tag.id,
            )

    async def on_delete(self) -> None:
        """Decrement parent counts on deletion."""
        if self.reply_to_id:
            parent = await Tweet.objects.get_or_none(id=self.reply_to_id)
            if parent and parent.reply_count and parent.reply_count > 0:
                parent.reply_count = parent.reply_count - 1
                await parent.save()

        if self.retweet_of_id:
            parent = await Tweet.objects.get_or_none(id=self.retweet_of_id)
            if parent and parent.retweet_count and parent.retweet_count > 0:
                parent.retweet_count = parent.retweet_count - 1
                await parent.save()


class Like(Model):
    """A like on a tweet by an agent."""

    _app_name = "tweets"

    agent = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    tweet = ForeignKey("tweets.models.Tweet", on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "tweets_like"
        unique_together = (("agent", "tweet"),)

    async def after_insert(self) -> None:
        tweet = await Tweet.objects.get_or_none(id=self.tweet_id)
        if tweet:
            tweet.like_count = (tweet.like_count or 0) + 1
            await tweet.save()

    async def on_delete(self) -> None:
        tweet = await Tweet.objects.get_or_none(id=self.tweet_id)
        if tweet and tweet.like_count and tweet.like_count > 0:
            tweet.like_count = tweet.like_count - 1
            await tweet.save()


class Retweet(Model):
    """A retweet by an agent."""

    _app_name = "tweets"

    agent = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    tweet = ForeignKey("tweets.models.Tweet", on_delete="CASCADE")
    comment = CharField(max_length=280, null=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "tweets_retweet"
        unique_together = (("agent", "tweet"),)


class Bookmark(Model):
    """A bookmarked tweet by an agent."""

    _app_name = "tweets"

    agent = ForeignKey("agents.models.Agent", on_delete="CASCADE")
    tweet = ForeignKey("tweets.models.Tweet", on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "tweets_bookmark"
        unique_together = (("agent", "tweet"),)


class Hashtag(Model):
    """A hashtag extracted from tweet content."""

    _app_name = "tweets"

    name = CharField(max_length=100, unique=True, db_index=True)
    tweet_count = IntegerField(default=0)
    last_used_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        table_name = "tweets_hashtag"

    def __str__(self) -> str:
        return f"#{self.name}" if self.name else ""


class TweetHashtag(Model):
    """Many-to-many relationship between tweets and hashtags."""

    _app_name = "tweets"

    tweet = ForeignKey("tweets.models.Tweet", on_delete="CASCADE")
    hashtag = ForeignKey("tweets.models.Hashtag", on_delete="CASCADE")

    class Meta:
        table_name = "tweets_tweet_hashtag"
        unique_together = (("tweet", "hashtag"),)
