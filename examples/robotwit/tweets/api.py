"""API routes for tweets."""

from __future__ import annotations

import typing as t

from agents.models import Agent

from openviper.auth.decorators import login_required
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.routing import Router
from tweets.models import Bookmark, Like, Retweet, Tweet

router = Router()


@router.get("/tweets")
async def list_tweets(request: Request) -> JSONResponse:
    """List tweets with cursor-based pagination."""
    cursor = request.query_params.get("cursor")
    limit = min(int(request.query_params.get("limit", "20")), 50)

    qs = Tweet.objects.filter(is_deleted=False).order_by("-created_at")
    if cursor:
        qs = qs.filter(created_at__lt=cursor)

    tweets = await qs.limit(limit).all()
    results = [await serialize_tweet(tw, request) for tw in tweets]
    next_cursor = str(tweets[-1].created_at) if tweets and len(tweets) >= limit else None
    return JSONResponse({"results": results, "next_cursor": next_cursor})


@router.get("/tweets/{tweet_id}")
async def get_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Get a single tweet by ID."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet or tweet.is_deleted:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)
    return JSONResponse(await serialize_tweet(tweet, request))


@router.post("/tweets")
@login_required
async def create_tweet(request: Request) -> JSONResponse:
    """Create a new tweet."""
    body = await request.json()
    content = body.get("content", "").strip()
    if not content or len(content) > 280:
        return JSONResponse({"error": "Content must be 1-280 characters"}, status_code=400)

    reply_to_id = body.get("reply_to_id")
    retweet_of_id = body.get("retweet_of_id")

    tweet = await Tweet.objects.create(
        author_id=request.user.id,
        content=content,
        reply_to_id=reply_to_id,
        retweet_of_id=retweet_of_id,
    )
    return JSONResponse(await serialize_tweet(tweet, request), status_code=201)


@router.delete("/tweets/{tweet_id}")
@login_required
async def delete_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Soft-delete a tweet (author only)."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)
    if tweet.author_id != request.user.id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    tweet.is_deleted = True
    await tweet.save()
    return JSONResponse({"deleted": True})


@router.post("/tweets/{tweet_id}/like")
@login_required
async def like_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Like a tweet."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet or tweet.is_deleted:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)

    existing = await Like.objects.get_or_none(agent_id=request.user.id, tweet_id=tweet_id)
    if existing:
        return JSONResponse({"liked": True, "like_count": tweet.like_count})

    await Like.objects.create(agent_id=request.user.id, tweet_id=tweet_id)
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    return JSONResponse({"liked": True, "like_count": tweet.like_count if tweet else 0})


@router.delete("/tweets/{tweet_id}/like")
@login_required
async def unlike_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Unlike a tweet."""
    existing = await Like.objects.get_or_none(agent_id=request.user.id, tweet_id=tweet_id)
    if not existing:
        return JSONResponse({"liked": False})

    await existing.delete()
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    return JSONResponse({"liked": False, "like_count": tweet.like_count if tweet else 0})


@router.post("/tweets/{tweet_id}/retweet")
@login_required
async def retweet_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Retweet a tweet."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet or tweet.is_deleted:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)

    existing = await Retweet.objects.get_or_none(agent_id=request.user.id, tweet_id=tweet_id)
    if existing:
        return JSONResponse({"retweeted": True, "retweet_count": tweet.retweet_count})

    body = await request.json()
    comment = body.get("comment", "").strip() or None

    await Retweet.objects.create(
        agent_id=request.user.id,
        tweet_id=tweet_id,
        comment=comment,
    )
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    return JSONResponse({"retweeted": True, "retweet_count": tweet.retweet_count if tweet else 0})


@router.post("/tweets/{tweet_id}/bookmark")
@login_required
async def bookmark_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Bookmark a tweet."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet or tweet.is_deleted:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)

    existing = await Bookmark.objects.get_or_none(agent_id=request.user.id, tweet_id=tweet_id)
    if not existing:
        await Bookmark.objects.create(agent_id=request.user.id, tweet_id=tweet_id)
    return JSONResponse({"bookmarked": True})


@router.delete("/tweets/{tweet_id}/bookmark")
@login_required
async def unbookmark_tweet(request: Request, tweet_id: int) -> JSONResponse:
    """Remove a bookmark."""
    existing = await Bookmark.objects.get_or_none(agent_id=request.user.id, tweet_id=tweet_id)
    if existing:
        await existing.delete()
    return JSONResponse({"bookmarked": False})


@router.get("/tweets/{tweet_id}/thread")
async def get_thread(request: Request, tweet_id: int) -> JSONResponse:
    """Get a tweet thread (all replies in the thread)."""
    tweet = await Tweet.objects.get_or_none(id=tweet_id)
    if not tweet or tweet.is_deleted:
        return JSONResponse({"error": "Tweet not found"}, status_code=404)

    root_id = tweet.thread_id_id or tweet.id
    replies = (
        await Tweet.objects.filter(
            thread_id=root_id,
            is_deleted=False,
        )
        .order_by("created_at")
        .all()
    )

    root_tweet = await Tweet.objects.get_or_none(id=root_id)
    results = [await serialize_tweet(root_tweet, request)] if root_tweet else []
    results.extend([await serialize_tweet(r, request) for r in replies])
    return JSONResponse({"thread": results})


@router.get("/bookmarks")
@login_required
async def list_bookmarks(request: Request) -> JSONResponse:
    """List bookmarked tweets."""
    bookmarks = (
        await Bookmark.objects.filter(
            agent_id=request.user.id,
        )
        .order_by("-created_at")
        .limit(20)
        .all()
    )

    tweet_ids = [b.tweet_id for b in bookmarks]
    tweets = await Tweet.objects.filter(id__in=tweet_ids, is_deleted=False).all()
    results = [await serialize_tweet(tw, request) for tw in tweets]
    return JSONResponse({"results": results})


async def serialize_tweet(tweet: Tweet, request: Request) -> dict[str, t.Any]:
    """Serialize a tweet for API response."""
    author = await tweet.author if hasattr(tweet, "author") else None
    if author is None:
        author = await Agent.objects.get_or_none(id=tweet.author_id)

    is_liked = False
    is_bookmarked = False
    if hasattr(request, "user") and request.user and request.user.is_authenticated:
        is_liked = (
            await Like.objects.get_or_none(
                agent_id=request.user.id,
                tweet_id=tweet.id,
            )
            is not None
        )
        is_bookmarked = (
            await Bookmark.objects.get_or_none(
                agent_id=request.user.id,
                tweet_id=tweet.id,
            )
            is not None
        )

    return {
        "id": tweet.id,
        "content": tweet.content,
        "author": {
            "id": author.id if author else None,
            "username": author.username if author else None,
            "display_name": author.display_name if author else None,
            "avatar_url": author.avatar_url if author else None,
        }
        if author
        else None,
        "like_count": tweet.like_count or 0,
        "retweet_count": tweet.retweet_count or 0,
        "reply_count": tweet.reply_count or 0,
        "is_liked": is_liked,
        "is_bookmarked": is_bookmarked,
        "reply_to_id": tweet.reply_to_id,
        "retweet_of_id": tweet.retweet_of_id,
        "created_at": str(tweet.created_at) if tweet.created_at else None,
    }
