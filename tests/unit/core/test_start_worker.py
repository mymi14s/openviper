"""Unit tests for start-worker management command."""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest

from openviper.core.management.commands.start_worker import Command


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestStartWorkerCommand:
    """Test start-worker command basic functionality."""

    def test_help_attribute(self, command) -> None:
        assert "task worker" in command.help.lower() or "worker" in command.help.lower()

    def test_add_arguments(self, command) -> None:
        parser = MagicMock()
        parser.add_argument = MagicMock()

        command.add_arguments(parser)

        # Should add modules, --queues, --threads, --processes
        assert parser.add_argument.call_count >= 4


class TestDramatiqImport:
    """Test dramatiq import handling."""

    def test_handle_missing_dramatiq_exits(self, command) -> None:
        """Test that missing dramatiq exits with error."""
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "dramatiq":
                raise ImportError("No module named 'dramatiq'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(SystemExit) as exc_info:
                command.handle(modules=[], queues=None, threads=8, processes=1)

        assert exc_info.value.code == 1
