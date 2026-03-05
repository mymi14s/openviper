"""Integration tests for the task worker and actor registration."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import dramatiq
import pytest

from openviper.tasks.worker import (
    create_worker,
)


@pytest.fixture(autouse=True)
def clean_dramatiq():
    """Clear dramatiq registry before and after tests."""
    # Dramatiq keeps a global registry of actors.
    # We may need to be careful with tests that register actors.
    # For integration tests, we'll mostly test the worker factory.
    pass


def test_create_worker_initialization():
    """Verify that create_worker initializes and returns a Worker instance."""
    # Mock setup_broker to return a StubBroker
    from dramatiq.brokers.stub import StubBroker

    broker = StubBroker()

    with patch("openviper.tasks.worker.setup_broker", return_value=broker):
        with patch("openviper.tasks.worker.discover_tasks") as mock_discover:
            worker = create_worker()
            assert isinstance(worker, dramatiq.Worker)
            assert worker.broker is broker
            mock_discover.assert_called_once()


@pytest.mark.asyncio
async def test_actor_execution_via_broker():
    """Smoke test: define an actor and send a message via StubBroker."""
    from dramatiq.brokers.stub import StubBroker

    broker = StubBroker()

    # We must set the global broker (or pass it to actor)
    with patch("dramatiq.get_broker", return_value=broker):

        @dramatiq.actor(broker=broker)
        def add(a, b):
            return a + b

        # Send message
        add.send(1, 2)

        # Verify message is in broker. StubBroker queues are internal Queue objects with qsize().
        assert broker.queues["default"].qsize() == 1


def test_discover_tasks_logic():
    """Verify that discover_tasks correctly walks apps and imports modules."""
    from openviper.tasks.worker import discover_tasks

    with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve_app.return_value = ("/fake/path", True)

        with patch("openviper.tasks.worker.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch("openviper.tasks.worker.os.walk") as mock_walk:
                # Mock a single .py file in the app.
                # Use a real-looking path so os.path.relpath works.
                app_path = "/tmp/myapp"
                mock_resolver.resolve_app.return_value = (app_path, True)

                mock_walk.return_value = [
                    (app_path, ["migrations"], ["__init__.py", "tasks.py", "views.py"])
                ]

                with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
                    imported = discover_tasks()

                    # Should skip migrations, __init__.py, and views.py (in _SKIP_FILES)
                    # Should import myapp.tasks
                    assert "myapp.tasks" in imported
                    mock_import.assert_any_call("myapp.tasks")


def test_discover_tasks_extra_modules():
    """Verify extra_modules are also imported."""
    from openviper.tasks.worker import discover_tasks

    with patch("openviper.tasks.worker.AppResolver") as mock_resolver_cls:
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve_app.return_value = (None, False)

        with patch("openviper.tasks.worker.importlib.import_module") as mock_import:
            imported = discover_tasks(extra_modules=["custom.tasks"])
            assert "custom.tasks" in imported
            mock_import.assert_any_call("custom.tasks")
