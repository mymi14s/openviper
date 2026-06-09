"""Tests for openviper.tasks.registry - actor and periodic registration."""

from __future__ import annotations

import typing as t

import pytest

from openviper.tasks.registry import Registry


class TestRegistry:
    """Test the task registry."""

    def setup_method(self) -> None:
        Registry().clear()

        registry = Registry()

        def identity(x: object) -> object:
            return x

        registry.register_actor("my_task", identity)
        assert registry.get_actor("my_task") is identity

    def test_get_unknown_actor_raises(self) -> None:
        registry = Registry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_actor("unknown")

    def test_duplicate_actor_raises(self) -> None:
        registry = Registry()
        registry.register_actor("dup", lambda: None)
        with pytest.raises(ValueError, match="already registered"):
            registry.register_actor("dup", lambda: None)

    def test_register_periodic(self) -> None:
        registry = Registry()
        registry.register_periodic("job1", schedule="60", every="60s")
        assert "job1" in registry.periodic_jobs
        assert registry.periodic_jobs["job1"]["every"] == "60s"

    def test_duplicate_periodic_raises(self) -> None:
        registry = Registry()
        registry.register_periodic("dup_job", schedule="60", every="60s")
        with pytest.raises(ValueError, match="already registered"):
            registry.register_periodic("dup_job", schedule="60", every="60s")

    def test_discovery_tracking(self) -> None:
        registry = Registry()
        assert not registry.is_discovered("myapp")
        registry.mark_discovered("myapp")
        assert registry.is_discovered("myapp")

    def test_clear_resets_all(self) -> None:
        registry = Registry()
        registry.register_actor("a", lambda: None)
        registry.register_periodic("b", schedule="60", every="60s")
        registry.mark_discovered("c")
        registry.clear()
        assert registry.actors == {}
        assert registry.periodic_jobs == {}
        assert not registry.is_discovered("c")

    def test_actors_snapshot(self) -> None:
        registry = Registry()
        registry.register_actor("snap", lambda: None)
        snap = registry.actors
        registry.register_actor("snap2", lambda: None)
        assert "snap2" not in snap
