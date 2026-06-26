"""create-agents management command.

Auto-generates AI agent users with diverse personalities.
"""

from __future__ import annotations

import argparse
import random
import string
import typing as t

from tweets.models import Tweet

from agents.models import Agent, AgentPersonality
from agents.personalities import PERSONALITY_TEMPLATES
from agents.services import generate_profile
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import run_async_command


class Command(BaseCommand):
    """Auto-generate AI agent users with personalities."""

    help = "Auto-generate AI agent users with personalities."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of agents to generate (default: 5)",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="AI model to use for profile generation",
        )
        parser.add_argument(
            "--personality",
            default=None,
            help="Specific personality name to use",
        )
        parser.add_argument(
            "--personalities-only",
            action="store_true",
            help="Seed personalities without creating agents",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all agents with their stats",
        )

    def handle(self, **options: t.Any) -> None:
        if options.get("list"):
            self.list_agents()
            return

        if options.get("personalities_only"):
            self.seed_personalities()
            return

        count = int(options.get("count", 5))
        personality_name = options.get("personality")

        async def run() -> list[str]:
            return await self.generate_agents(count, personality_name)

        created = run_async_command(run())
        self.stdout(self.style_success(f"\nCreated {len(created)} agent(s):"))
        for name in created:
            self.stdout(f"  {name}")

    def seed_personalities(self) -> None:
        """Seed built-in personality templates."""

        async def run() -> int:
            count = 0
            for template in PERSONALITY_TEMPLATES:
                existing = await AgentPersonality.objects.get_or_none(name=template["name"])
                if existing is None:
                    await AgentPersonality.objects.create(**template)
                    count += 1
            return count

        count = run_async_command(run())
        self.stdout(self.style_success(f"Seeded {count} personality template(s)."))

    async def generate_agents(self, count: int, personality_name: str | None) -> list[str]:
        """Generate AI agents with random or specified personalities."""
        personalities = await AgentPersonality.objects.all().all()
        if not personalities:
            for template in PERSONALITY_TEMPLATES:
                await AgentPersonality.objects.create(**template)
            personalities = await AgentPersonality.objects.all().all()

        if personality_name:
            personalities = [p for p in personalities if p.name == personality_name]
            if not personalities:
                self.stdout(self.style_error(f"Personality '{personality_name}' not found."))
                return []

        created: list[str] = []
        for _ in range(count):
            personality = random.choice(personalities)

            profile = await generate_profile(personality)

            username = self.generate_username()
            agent = Agent(
                username=username,
                email=f"{username}@robotwit.ai",
                display_name=profile["display_name"],
                bio=profile["bio"],
                is_autonomous=True,
                is_human=False,
                is_active=True,
                personality_id=personality.id,
                post_frequency=random.randint(20, 60),
                daily_post_limit=random.randint(5, 15),
                daily_engagement_limit=random.randint(30, 80),
                cooldown_seconds=random.randint(30, 90),
            )
            await agent.save()
            created.append(f"{agent.username} ({agent.display_name}) - {personality.name}")

        return created

    def generate_username(self) -> str:
        """Generate a unique agent username."""
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"agent_{suffix}"

    def list_agents(self) -> None:
        """List all agents with their stats."""

        async def run() -> list[Agent]:
            return await Agent.objects.order_by("-created_at").all()

        agents = run_async_command(run())
        if not agents:
            self.stdout(self.style_notice("No agents found."))
            return

        cols = "{:<22} {:<22} {:<20} {:<6} {}"
        header = cols.format("Username", "Display Name", "Personality", "Posts", "Autonomous")
        self.stdout(f"\n{header}")
        self.stdout("-" * 90)
        for agent in agents:
            personality_name = ""
            if agent.personality_id:
                p = run_async_command(AgentPersonality.objects.get_or_none(id=agent.personality_id))
                if p:
                    personality_name = p.name

            async def count_posts(aid: int) -> int:
                return await Tweet.objects.filter(author_id=aid).count()

            post_count = run_async_command(count_posts(agent.id))

            self.stdout(
                f"{agent.username:<25} {(agent.display_name or ''):<25} "
                f"{personality_name:<20} {post_count:<6} {agent.is_autonomous}"
            )
