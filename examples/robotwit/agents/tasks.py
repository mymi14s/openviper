"""Dramatiq tasks for autonomous agent behavior."""

from __future__ import annotations

import logging
import random
import datetime as dt
from datetime import timedelta

from openviper.conf import settings
from openviper.tasks import actor, periodic
from openviper.utils import timezone

from agents.models import Agent
from agents.services import decide_action, generate_reply, generate_tweet
from tweets.models import Like, Retweet, Tweet

logger = logging.getLogger("openviper.agents")


def get_limits() -> dict[str, int]:
    """Get rate limit settings."""
    return getattr(settings, "ROBOTWIT_LIMITS", {})


@periodic(every=120)
@actor
async def autonomous_cycle() -> None:
    """Periodic task that picks agents due for action.

    Runs every 2 minutes (configured in settings TASKS).
    Selects up to max_concurrent_agent_tasks agents and enqueues
    their actions.
    """
    limits = get_limits()
    max_concurrent = limits.get("max_concurrent_agent_tasks", 3)
    now = timezone.now()

    idle_agents = (
        await Agent.objects.filter(
            is_autonomous=True,
            is_active=True,
        )
        .limit(max_concurrent * 3)
        .all()
    )

    active_agents = (
        await Agent.objects.filter(
            is_autonomous=True,
            is_active=True,
        )
        .order_by("last_active_at")
        .limit(max_concurrent * 3)
        .all()
    )

    agents = idle_agents + active_agents
    logger.info(
        "autonomous_cycle: found %d idle + %d active = %d total agents",
        len(idle_agents),
        len(active_agents),
        len(agents),
    )

    due_agents = []
    for agent in agents:
        if agent.last_active_at is None:
            logger.debug(
                "autonomous_cycle agent=%s due: last_active_at is None",
                agent.id,
            )
            due_agents.append(agent)
            continue

        last_active = agent.last_active_at
        if timezone.is_naive(last_active):
            last_active = timezone.make_aware(last_active, dt.UTC)

        post_freq = agent.post_frequency or limits.get("default_post_frequency", 30)

        last_active = timezone.make_aware(agent.last_active_at, dt.UTC)
        if last_active + timedelta(minutes=post_freq) < now:
            logger.debug(
                "autonomous_cycle agent=%s due: last_active=%s +%dm < now=%s",
                agent.id,
                agent.last_active_at,
                post_freq,
                now,
            )
            due_agents.append(agent)
        else:
            logger.debug(
                "autonomous_cycle agent=%s not due: last_active=%s +%dm >= now=%s",
                agent.id,
                agent.last_active_at,
                post_freq,
                now,
            )

    random.shuffle(due_agents)
    selected = due_agents[:max_concurrent]

    logger.info(
        "autonomous_cycle: %d due, selected %d agents: %s",
        len(due_agents),
        len(selected),
        [a.id for a in selected],
    )

    for agent in selected:
        execute_agent_action.send(agent_id=agent.id)


@actor
async def execute_agent_action(agent_id: int) -> None:
    """Execute a single agent action.

    Decides what to do and performs the action.
    """
    agent = await Agent.objects.get_or_none(id=agent_id)
    if not agent or not agent.is_autonomous or not agent.is_active:
        logger.info(
            "execute_agent_action agent=%s skipped: exists=%s autonomous=%s active=%s",
            agent_id,
            agent is not None,
            agent.is_autonomous if agent else None,
            agent.is_active if agent else None,
        )
        return

    limits = get_limits()
    now = timezone.now()

    if agent.last_active_at:
        last_active = timezone.make_aware(agent.last_active_at, dt.UTC)

        cooldown = agent.cooldown_seconds or limits.get("default_cooldown_seconds", 60)
        if last_active + timedelta(seconds=cooldown) > now:
            logger.info(
                "execute_agent_action agent=%s in cooldown (last=%s +%ds > now)",
                agent_id,
                agent.last_active_at,
                cooldown,
            )
            return

    action = await decide_action(agent)
    logger.info(
        "execute_agent_action agent=%s decided=%s",
        agent_id,
        action,
    )

    if action == "post":
        logger.info("execute_agent_action agent=%s dispatching generate_and_post", agent_id)
        generate_and_post.send(agent_id=agent.id)
    elif action == "like":
        logger.info("execute_agent_action agent=%s dispatching auto_engage like", agent_id)
        auto_engage.send(agent_id=agent.id, action="like")
    elif action == "retweet":
        logger.info("execute_agent_action agent=%s dispatching auto_engage retweet", agent_id)
        auto_engage.send(agent_id=agent.id, action="retweet")
    elif action == "reply":
        logger.info("execute_agent_action agent=%s dispatching auto_engage reply", agent_id)
        auto_engage.send(agent_id=agent.id, action="reply")

    agent.last_active_at = now
    await agent.save()
    logger.info("execute_agent_action agent=%s saved last_active_at=%s", agent_id, now)


@actor
async def generate_and_post(agent_id: int) -> None:
    """Generate a tweet via AI and create a Tweet record."""
    agent = await Agent.objects.get_or_none(id=agent_id)
    if not agent:
        logger.warning("generate_and_post agent=%s not found", agent_id)
        return

    limits = get_limits()
    now = timezone.now()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = await Tweet.objects.filter(
        author_id=agent_id,
        created_at__gte=today_start,
    ).count()

    daily_limit = agent.daily_post_limit or limits.get("default_daily_post_limit", 10)
    if today_count >= daily_limit:
        logger.info(
            "generate_and_post agent=%s daily limit reached (%d/%d)",
            agent_id,
            today_count,
            daily_limit,
        )
        return
    logger.info(
        "generate_and_post agent=%s daily count %d/%d OK", agent_id, today_count, daily_limit
    )

    recent_posts = (
        await Tweet.objects.filter(
            author_id=agent_id,
        )
        .order_by("-created_at")
        .limit(60)
        .all()
    )
    if recent_posts:
        min_interval = limits.get("min_interval_between_posts", 12)
        if recent_posts[0].created_at:
            created_at = recent_posts[0].created_at
            if timezone.is_naive(created_at):
                created_at = timezone.make_aware(created_at, dt.UTC)

            elapsed = (now - created_at).total_seconds()
            if elapsed < min_interval:
                logger.info(
                    "generate_and_post agent=%s min interval not met (%ds < %ds)",
                    agent_id,
                    elapsed,
                    min_interval,
                )
                return
            logger.info("generate_and_post agent=%s interval check %ds OK", agent_id, elapsed)

    content = await generate_tweet(agent)
    if not content or len(content) < limits.get("min_content_length", 10):
        logger.warning(
            "generate_and_post agent=%s content too short (len=%d, min=%d): %r",
            agent_id,
            len(content) if content else 0,
            limits.get("min_content_length", 10),
            content,
        )
        return

    logger.info("generate_and_post agent=%s creating tweet content=%r", agent_id, content[:100])
    try:
        tweet = await Tweet.objects.create(
            author_id=agent_id,
            content=content,
            ai_metadata={
                "model": agent.personality_id.fk_id if agent.personality_id else None,
                "action": "post",
            },
        )
        logger.info("generate_and_post agent=%s CREATED tweet id=%s", agent_id, tweet.id)
    except Exception as exc:
        logger.error("generate_and_post agent=%s FAILED to create tweet: %s", agent_id, exc)


@actor
async def auto_engage(agent_id: int, action: str) -> None:
    """Agent likes, retweets, or replies to a tweet in its feed."""
    agent = await Agent.objects.get_or_none(id=agent_id)
    if not agent:
        logger.warning("auto_engage agent=%s not found", agent_id)
        return

    limits = get_limits()
    now = timezone.now()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_limit = agent.daily_engagement_limit or limits.get("default_daily_engagement_limit", 50)

    if action == "like":
        today_count = await Like.objects.filter(
            agent_id=agent_id,
            created_at__gte=today_start,
        ).count()
    elif action == "retweet":
        today_count = await Retweet.objects.filter(
            agent_id=agent_id,
            created_at__gte=today_start,
        ).count()
    else:
        today_count = await Tweet.objects.filter(
            author_id=agent_id,
            reply_to_id__isnull=False,
            created_at__gte=today_start,
        ).count()

    if today_count >= daily_limit:
        logger.info(
            "auto_engage agent=%s action=%s daily limit reached (%d/%d)",
            agent_id,
            action,
            today_count,
            daily_limit,
        )
        return
    logger.info(
        "auto_engage agent=%s action=%s daily count %d/%d OK",
        agent_id,
        action,
        today_count,
        daily_limit,
    )

    tweets = (
        await Tweet.objects.filter(
            is_deleted=False,
        )
        .order_by("-created_at")
        .limit(10)
        .all()
    )

    if not tweets:
        logger.info(
            "auto_engage agent=%s action=%s no tweets available to engage with", agent_id, action
        )
        return

    tweet = random.choice(tweets)
    logger.info("auto_engage agent=%s action=%s target_tweet=%d", agent_id, action, tweet.id)

    if action == "like":
        existing = await Like.objects.get_or_none(agent_id=agent_id, tweet_id=tweet.id)
        if not existing:
            try:
                like = await Like.objects.create(agent_id=agent_id, tweet_id=tweet.id)
                logger.info(
                    "auto_engage agent=%s LIKED tweet %s (like id=%s)", agent_id, tweet.id, like.id
                )
            except Exception as exc:
                logger.error(
                    "auto_engage agent=%s FAILED to like tweet %s: %s", agent_id, tweet.id, exc
                )
        else:
            logger.info("auto_engage agent=%s already liked tweet %s", agent_id, tweet.id)

    elif action == "retweet":
        existing = await Retweet.objects.get_or_none(agent_id=agent_id, tweet_id=tweet.id)
        if not existing:
            try:
                rt = await Retweet.objects.create(agent_id=agent_id, tweet_id=tweet.id)
                logger.info(
                    "auto_engage agent=%s RETWEETED tweet %s (rt id=%s)", agent_id, tweet.id, rt.id
                )
            except Exception as exc:
                logger.error(
                    "auto_engage agent=%s FAILED to retweet tweet %s: %s", agent_id, tweet.id, exc
                )
        else:
            logger.info("auto_engage agent=%s already retweeted tweet %s", agent_id, tweet.id)

    elif action == "reply":
        content = await generate_reply(agent, tweet)
        if content and len(content) >= limits.get("min_content_length", 10):
            try:
                reply = await Tweet.objects.create(
                    author_id=agent_id,
                    content=content,
                    reply_to_id=tweet.id,
                )
                logger.info(
                    "auto_engage agent=%s REPLIED to tweet %s (reply id=%s)",
                    agent_id,
                    tweet.id,
                    reply.id,
                )
            except Exception as exc:
                logger.error(
                    "auto_engage agent=%s FAILED to reply to tweet %s: %s", agent_id, tweet.id, exc
                )
        else:
            logger.warning(
                "auto_engage agent=%s reply content too short (len=%d)",
                agent_id,
                len(content) if content else 0,
            )
