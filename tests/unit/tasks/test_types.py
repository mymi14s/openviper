"""Tests for openviper.tasks.types - TaskMessageProxy."""

from __future__ import annotations

import pytest

from openviper.tasks.exceptions import ResultsBackendDisabledError
from openviper.tasks.types import TaskMessageProxy


class TestTaskMessageProxy:
    """Test the TaskMessageProxy data carrier."""

    def test_proxy_stores_attributes(self) -> None:
        proxy = TaskMessageProxy(
            actor_name="send_email",
            args=("alice@example.com",),
            kwargs={"subject": "Hi"},
            queue_name="emails",
            message_id="msg-123",
        )
        assert proxy.actor_name == "send_email"
        assert proxy.queue_name == "emails"
        assert proxy.message_id == "msg-123"

    def test_proxy_default_queue(self) -> None:
        proxy = TaskMessageProxy(
            actor_name="task",
            args=(),
            kwargs={},
        )
        assert proxy.queue_name == "default"

    def test_get_result_raises_without_backend(self) -> None:
        proxy = TaskMessageProxy(
            actor_name="task",
            args=(),
            kwargs={},
        )
        with pytest.raises(ResultsBackendDisabledError):
            proxy.get_result()
