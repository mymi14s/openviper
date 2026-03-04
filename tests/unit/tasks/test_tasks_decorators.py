from unittest.mock import patch

import dramatiq
import pytest

from openviper.tasks.broker import reset_broker
from openviper.tasks.decorators import task


@pytest.fixture(autouse=True)
def setup_tasks():
    reset_broker()
    with patch("openviper.tasks.broker._read_task_settings", return_value={"broker": "stub"}):
        yield
    reset_broker()


def test_task_decorator():
    @task(queue_name="high", priority=10)
    def my_task(x, y):
        return x + y

    assert isinstance(my_task, dramatiq.Actor)
    assert my_task.queue_name == "high"
    assert my_task.priority == 10
    assert hasattr(my_task, "delay")


def test_task_execution_stub():
    @task()
    def add(x, y):
        return x + y

    broker = add.broker
    # In stub broker, we can check messages in the queue
    add.send(1, 2)
    # Correct way to check messages in StubBroker: broker.queues["default"] is a Queue object
    assert broker.queues["default"].qsize() == 1


def test_task_with_time_limit():
    """Line 88: time_limit is added to actor_kwargs when not None."""

    @task(time_limit=5000)
    def limited_task():
        pass

    assert limited_task.options.get("time_limit") == 5000


def test_task_without_time_limit_has_no_time_limit_option():
    """time_limit=None (default) means time_limit is NOT in actor options."""

    @task()
    def unlimited_task():
        pass

    assert "time_limit" not in unlimited_task.options
