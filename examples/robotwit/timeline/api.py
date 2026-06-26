"""API routes for timeline and social graph."""

from __future__ import annotations

from agents.models import Agent
from tweets.api import serialize_tweet
from tweets.models import Hashtag, Tweet, TweetHashtag

from openviper.auth.decorators import login_required
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.routing import Router
from timeline.models import Follow

router = Router()


@router.get("/timeline/home")
@login_required
async def home_timeline(request: Request) -> JSONResponse:
    """Personalized timeline from followed agents."""
    cursor = request.query_params.get("cursor")
    limit = min(int(request.query_params.get("limit", "20")), 50)

    follows = await Follow.objects.filter(follower_id=request.user.id).all()
    following_ids = [f.following_id for f in follows]
    following_ids.append(request.user.id)

    qs = Tweet.objects.filter(
        author_id__in=following_ids,
        is_deleted=False,
    ).order_by("-created_at")

    if cursor:
        qs = qs.filter(created_at__lt=cursor)

    tweets = await qs.limit(limit).all()
    results = [await serialize_tweet(tw, request) for tw in tweets]
    next_cursor = str(tweets[-1].created_at) if tweets and len(tweets) >= limit else None
    return JSONResponse({"results": results, "next_cursor": next_cursor})


@router.get("/timeline/explore")
async def explore_timeline(request: Request) -> JSONResponse:
    """All tweets for exploration."""
    cursor = request.query_params.get("cursor")
    limit = min(int(request.query_params.get("limit", "20")), 50)

    qs = Tweet.objects.filter(is_deleted=False).order_by("-created_at")
    if cursor:
        qs = qs.filter(created_at__lt=cursor)

    tweets = await qs.limit(limit).all()
    results = [await serialize_tweet(tw, request) for tw in tweets]
    next_cursor = str(tweets[-1].created_at) if tweets and len(tweets) >= limit else None
    return JSONResponse({"results": results, "next_cursor": next_cursor})


@router.get("/agents/{agent_id}")
async def get_agent(request: Request, agent_id: int) -> JSONResponse:
    """Get an agent's profile."""
    agent = await Agent.objects.get_or_none(id=agent_id)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    is_following = False
    if hasattr(request, "user") and request.user and request.user.is_authenticated:
        is_following = (
            await Follow.objects.get_or_none(
                follower_id=request.user.id,
                following_id=agent_id,
            )
            is not None
        )

    return JSONResponse(
        {
            "id": agent.id,
            "username": agent.username,
            "display_name": agent.display_name,
            "bio": agent.bio,
            "avatar_url": agent.avatar_url,
            "is_autonomous": agent.is_autonomous,
            "is_human": agent.is_human,
            "follower_count": agent.follower_count or 0,
            "following_count": agent.following_count or 0,
            "is_following": is_following,
            "created_at": str(agent.created_at) if agent.created_at else None,
        }
    )


@router.get("/agents/{agent_id}/tweets")
async def agent_tweets(request: Request, agent_id: int) -> JSONResponse:
    """Get an agent's tweets."""
    cursor = request.query_params.get("cursor")
    limit = min(int(request.query_params.get("limit", "20")), 50)

    qs = Tweet.objects.filter(
        author_id=agent_id,
        is_deleted=False,
    ).order_by("-created_at")

    if cursor:
        qs = qs.filter(created_at__lt=cursor)

    tweets = await qs.limit(limit).all()
    results = [await serialize_tweet(tw, request) for tw in tweets]
    next_cursor = str(tweets[-1].created_at) if tweets and len(tweets) >= limit else None
    return JSONResponse({"results": results, "next_cursor": next_cursor})


@router.post("/agents/{agent_id}/follow")
@login_required
async def follow_agent(request: Request, agent_id: int) -> JSONResponse:
    """Follow an agent."""
    if agent_id == request.user.id:
        return JSONResponse({"error": "Cannot follow yourself"}, status_code=400)

    agent = await Agent.objects.get_or_none(id=agent_id)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    existing = await Follow.objects.get_or_none(
        follower_id=request.user.id,
        following_id=agent_id,
    )
    if existing:
        return JSONResponse({"following": True, "follower_count": agent.follower_count})

    await Follow.objects.create(follower_id=request.user.id, following_id=agent_id)
    agent = await Agent.objects.get_or_none(id=agent_id)
    return JSONResponse(
        {
            "following": True,
            "follower_count": agent.follower_count if agent else 0,
        }
    )


@router.delete("/agents/{agent_id}/follow")
@login_required
async def unfollow_agent(request: Request, agent_id: int) -> JSONResponse:
    """Unfollow an agent."""
    existing = await Follow.objects.get_or_none(
        follower_id=request.user.id,
        following_id=agent_id,
    )
    if not existing:
        return JSONResponse({"following": False})

    await existing.delete()
    agent = await Agent.objects.get_or_none(id=agent_id)
    return JSONResponse(
        {
            "following": False,
            "follower_count": agent.follower_count if agent else 0,
        }
    )


@router.get("/search")
async def search_tweets(request: Request) -> JSONResponse:
    """Search tweets by content."""
    q = request.query_params.get("q", "").strip()
    if not q or len(q) < 2:
        return JSONResponse({"results": []})

    tweets = (
        await Tweet.objects.filter(
            is_deleted=False,
            content__contains=q,
        )
        .order_by("-created_at")
        .limit(20)
        .all()
    )

    results = [await serialize_tweet(tw, request) for tw in tweets]
    return JSONResponse({"results": results})


@router.get("/search/agents")
async def search_agents(request: Request) -> JSONResponse:
    """Search agents by name or bio."""
    q = request.query_params.get("q", "").strip()
    if not q or len(q) < 2:
        return JSONResponse({"results": []})

    agents = (
        await Agent.objects.filter(
            is_active=True,
            display_name__contains=q,
        )
        .limit(20)
        .all()
    )

    results = [
        {
            "id": a.id,
            "username": a.username,
            "display_name": a.display_name,
            "bio": a.bio,
            "avatar_url": a.avatar_url,
            "follower_count": a.follower_count or 0,
        }
        for a in agents
    ]
    return JSONResponse({"results": results})


@router.get("/trending/hashtags")
async def trending_hashtags(request: Request) -> JSONResponse:
    """Get trending hashtags."""
    hashtags = await Hashtag.objects.order_by("-tweet_count").limit(10).all()
    results = [
        {
            "name": h.name,
            "tweet_count": h.tweet_count or 0,
        }
        for h in hashtags
    ]
    return JSONResponse({"results": results})


@router.get("/hashtags/{name}")
async def tweets_by_hashtag(request: Request, name: str) -> JSONResponse:
    """Get tweets by hashtag name."""
    hashtag = await Hashtag.objects.get_or_none(name=name.lower())
    if not hashtag:
        return JSONResponse({"results": []})

    links = await TweetHashtag.objects.filter(hashtag_id=hashtag.id).limit(20).all()
    tweet_ids = [link.tweet_id for link in links]
    tweets = (
        await Tweet.objects.filter(
            id__in=tweet_ids,
            is_deleted=False,
        )
        .order_by("-created_at")
        .all()
    )

    results = [await serialize_tweet(tw, request) for tw in tweets]
    return JSONResponse({"results": results})
