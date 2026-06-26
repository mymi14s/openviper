"""Unit tests for rate limiting logic."""

from __future__ import annotations

from openviper.conf import settings


class TestRateLimits:
    """Test rate limit configuration and logic."""

    def test_limits_config_exists(self) -> None:
        limits = getattr(settings, "ROBOTWIT_LIMITS", {})
        assert "max_concurrent_agent_tasks" in limits
        assert "global_post_rate_limit" in limits
        assert "min_interval_between_posts" in limits
        assert "default_post_frequency" in limits
        assert "default_daily_post_limit" in limits
        assert "default_daily_engagement_limit" in limits
        assert "default_cooldown_seconds" in limits

    def test_agent_generation_config_exists(self) -> None:
        config = getattr(settings, "ROBOTWIT_AGENT_GENERATION", {})
        assert "default_model" in config
        assert "username_prefix" in config
        assert "min_post_frequency" in config
        assert "max_post_frequency" in config

    def test_limits_are_reasonable(self) -> None:
        limits = getattr(settings, "ROBOTWIT_LIMITS", {})
        assert limits.get("max_concurrent_agent_tasks", 0) > 0
        assert limits.get("max_concurrent_agent_tasks", 99) <= 10
        assert limits.get("default_post_frequency", 0) >= 10
        assert limits.get("default_daily_post_limit", 0) > 0
        assert limits.get("default_daily_post_limit", 99) <= 50
