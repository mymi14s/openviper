"""Seed default personality templates."""

from __future__ import annotations

from openviper.db.patches import db_patch

from agents.management.commands.create_agents import Command


@db_patch
async def create_bot_fleet():
    print("Seeding default personality templates...")
    command = Command()

    agents = await command.generate_agents(
        count=10,
        personality_name="",
    )

    return agents
