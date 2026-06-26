"""AI services for agent content generation and action decisions."""

from __future__ import annotations

import json
import logging
import random
import re

from tweets.models import Tweet

from agents.models import Agent, AgentPersonality
from openviper.ai.router import model_router
from openviper.conf import settings

logger = logging.getLogger("openviper.agents")


def _extract_json(text: str) -> dict[str, str] | None:
    """Try to extract a JSON object from potentially noisy model output."""
    text = text.strip()
    # Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Find JSON object via regex (handles extra text before/after)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return None


async def get_ai_provider():
    """Get the configured AI provider by default model ID."""
    default_model = getattr(settings, "AI_DEFAULT_MODEL", None)
    if not default_model:
        logger.warning("get_ai_provider: AI_DEFAULT_MODEL is not set")
        return None
    try:
        provider = model_router.get_provider(default_model)
        logger.info(
            "get_ai_provider: resolved provider %s for model %s",
            type(provider).__name__,
            default_model,
        )
        return provider
    except Exception as exc:
        logger.error("get_ai_provider: failed to get provider for model %s: %s", default_model, exc)
        return None


async def generate_tweet(agent: Agent) -> str:
    """Generate a tweet for an agent based on its personality."""
    provider = await get_ai_provider()
    if not provider:
        return "Exploring new ideas today."

    personality = None
    if agent.personality_id:
        personality = await AgentPersonality.objects.get_or_none(id=agent.personality_id)

    system_prompt = "You are a social media user. Write a short, engaging tweet."
    if personality:
        system_prompt = personality.system_prompt
        temperature = personality.temperature or 0.8
    else:
        temperature = 0.8

    interests = personality.interests if personality and personality.interests else []
    interests_str = ", ".join(interests) if interests else "general topics"

    prompt = (
        f"Write a single tweet (max 280 characters) about {interests_str}. "
        "Be original, engaging, and authentic. Do not use hashtags excessively. "
        "Return only the tweet text, no quotes or explanations."
    )

    try:
        response = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=100,
        )
        logger.info(
            "generate_tweet agent=%s raw_response=%r",
            agent.id,
            response[:200] if response else "(empty)",
        )
        content = response.strip().strip('"').strip("'")
        if len(content) > 280:
            content = content[:277] + "..."
        logger.info(
            "generate_tweet agent=%s final_content=%r len=%d",
            agent.id,
            content[:100],
            len(content),
        )
        return content
    except Exception as exc:
        logger.error("AI generation failed for agent %s: %s", agent.id, exc)
        return "Having thoughts today."


async def decide_action(agent: Agent) -> str:
    """Decide what action an agent should take.

    Returns one of:
    'post', 'like', 'retweet', 'reply'
    """

    valid_actions = {
        "post",
        "like",
        "retweet",
        "reply",
    }

    return random.choice(list(valid_actions))


async def generate_reply(agent: Agent, tweet: Tweet) -> str:
    """Generate a reply to a specific tweet."""
    provider = await get_ai_provider()
    if not provider:
        return "Interesting perspective."

    personality = None
    if agent.personality_id:
        personality = await AgentPersonality.objects.get_or_none(id=agent.personality_id)

    system_prompt = personality.system_prompt if personality else "You are a social media user."

    prompt = (
        f"Reply to this tweet (max 280 characters):\n"
        f'"{tweet.content}"\n\n'
        "Write a thoughtful, engaging reply. Return only the reply text."
    )

    try:
        response = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=100,
        )
        content = response.strip().strip('"').strip("'")
        if len(content) > 280:
            content = content[:277] + "..."
        return content
    except Exception as exc:
        logger.error("Reply generation failed: %s", exc)
        return "Great point!"


async def generate_profile(personality: AgentPersonality) -> dict[str, str]:
    """Generate a display name and bio for a new agent."""
    provider = await get_ai_provider()
    if not provider:
        return {
            "display_name": personality.name,
            "bio": f"An AI agent with the {personality.name} personality.",
        }

    prompt = (
        f"Create a social media profile for an AI agent with this personality:\n"
        f"Name: {personality.name}\n"
        f"Traits: {personality.traits}\n"
        f"Interests: {personality.interests}\n\n"
        "Return JSON with 'display_name' (max 50 chars) and 'bio' (max 160 chars)."
    )

    try:
        response = await provider.generate(
            prompt=prompt,
            system_prompt="You create social media profiles.",
            temperature=0.8,
            max_tokens=200,
        )
        data = _extract_json(response.strip())
        if data is not None:
            return {
                "display_name": str(data.get("display_name", personality.name))[:50],
                "bio": str(data.get("bio", ""))[:160],
            }
        # Fallback: try line-by-line extraction
        lines = response.strip().split("\n")
        display_name = personality.name
        bio = ""
        for line in lines:
            line = line.strip().strip('"').strip("'").strip(",")
            if line.lower().startswith("display_name") or line.lower().startswith('"display_name'):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    display_name = parts[1].strip().strip('"').strip("'").strip(",")[:50]
            elif line.lower().startswith("bio") or line.lower().startswith('"bio'):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    bio = parts[1].strip().strip('"').strip("'").strip(",")[:160]
        if display_name != personality.name or bio:
            return {"display_name": display_name, "bio": bio}
        raise ValueError("Could not extract profile from response")
    except Exception as exc:
        logger.error("Profile generation failed: %s", exc)
        return {
            "display_name": personality.name,
            "bio": f"An AI agent with the {personality.name} personality.",
        }
