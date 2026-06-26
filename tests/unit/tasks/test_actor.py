"""Tests for openviper.tasks.decorators - actor decorator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openviper.tasks.decorators import actor
from openviper.tasks.registry import Registry
from openviper.tasks.types import TaskMessageProxy


class TestActorDecorator:
    """Test the @actor decorator and its proxy methods."""

    def setup_method(self) -> None:
        Registry().clear()

    def test_actor_registers_function(self) -> None:
        @actor
        async def my_task(x: int) -> int:
            return x + 1

        registry = Registry()
        assert my_task.actor_name in registry.actors

    def test_actor_with_custom_name(self) -> None:
        @actor(actor_name="custom.task_name")
        async def another_task() -> None:
            pass

        registry = Registry()
        assert "custom.task_name" in registry.actors

    def test_actor_with_queue_name(self) -> None:
        @actor(queue_name="emails")
        async def email_task() -> None:
            pass

        assert hasattr(email_task, "queue_name")
        assert email_task.queue_name == "emails"

    def test_actor_send_returns_proxy(self) -> None:
        @actor
        async def proxy_task(x: int) -> int:
            return x

        with patch("openviper.tasks.decorators.enqueue_task") as mock_enqueue:
            mock_enqueue.return_value = TaskMessageProxy(
                actor_name=proxy_task.actor_name, args=(42,), kwargs={}, queue_name="default"
            )
            proxy = proxy_task.send(42)
            assert proxy.actor_name == proxy_task.actor_name

    def test_actor_send_with_options_returns_proxy(self) -> None:
        @actor
        async def opts_task(x: int) -> int:
            return x

        with patch("openviper.tasks.decorators.enqueue_task") as mock_enqueue:
            mock_enqueue.return_value = TaskMessageProxy(
                actor_name=opts_task.actor_name, args=(99,), kwargs={}, queue_name="default"
            )
            proxy = opts_task.send_with_options(args=(99,), delay=5000)
            assert proxy.actor_name == opts_task.actor_name

    def test_actor_message_returns_dict(self) -> None:
        @actor
        async def msg_task(x: int) -> int:
            return x

        msg = msg_task.message(7)
        assert isinstance(msg, dict)
        assert msg["args"] == (7,)
        assert "actor_name" in msg

    def test_duplicate_actor_name_raises(self) -> None:
        @actor(actor_name="dup_task")
        async def first() -> None:
            pass

        with pytest.raises(ValueError, match="already registered"):

            @actor(actor_name="dup_task")
            async def second() -> None:
                pass

    def test_sync_fallback_when_disabled(self) -> None:
        """When TASKS['enabled'] == 0, .send() executes synchronously."""
        @actor(actor_name="sync_fallback_task")
        def sync_task(x: int) -> int:
            return x * 2

        with patch("openviper.tasks.decorators.enqueue_task") as mock_enqueue:
            mock_enqueue.return_value = TaskMessageProxy(
                actor_name="sync_fallback_task", args=(5,), kwargs={}, queue_name="default"
            )
            result = sync_task.send(5)
            assert result.actor_name == "sync_fallback_task"

    def test_get_result_delegates_to_proxy(self) -> None:
        """The .get_result() method on the actor wrapper delegates to TaskMessageProxy."""
        @actor(actor_name="get_result_task")
        async def gr_task(x: int) -> int:
            return x

        with patch("openviper.tasks.decorators.enqueue_task") as mock_enqueue:
            mock_enqueue.return_value = TaskMessageProxy(
                actor_name="get_result_task", args=(1,), kwargs={}, queue_name="default"
            )
            gr_task.send(1)
            assert hasattr(gr_task, "get_result")
