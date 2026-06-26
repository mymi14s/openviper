"""Admin registration for tweets app."""

from __future__ import annotations

from openviper.admin import ModelAdmin, register
from tweets.models import Bookmark, Hashtag, Like, Retweet, Tweet, TweetHashtag


@register(Tweet)
class TweetAdmin(ModelAdmin):
    list_display = [
        "id",
        "author",
        "content",
        "like_count",
        "retweet_count",
        "reply_count",
        "is_deleted",
        "is_flagged",
        "created_at",
    ]
    list_filter = ["is_deleted", "is_flagged", "created_at"]
    search_fields = ["content"]


@register(Like)
class LikeAdmin(ModelAdmin):
    list_display = ["id", "agent", "tweet", "created_at"]
    list_filter = ["created_at"]


@register(Retweet)
class RetweetAdmin(ModelAdmin):
    list_display = ["id", "agent", "tweet", "comment", "created_at"]
    list_filter = ["created_at"]


@register(Bookmark)
class BookmarkAdmin(ModelAdmin):
    list_display = ["id", "agent", "tweet", "created_at"]


@register(Hashtag)
class HashtagAdmin(ModelAdmin):
    list_display = ["id", "name", "tweet_count", "last_used_at"]
    search_fields = ["name"]
    list_filter = ["last_used_at"]


@register(TweetHashtag)
class TweetHashtagAdmin(ModelAdmin):
    list_display = ["id", "tweet", "hashtag"]
