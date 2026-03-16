"""Unit tests for openviper/tasks/__init__.py — OPENVIPER_WORKER bootstrap."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import MagicMock, patch


def _reload_tasks_with_worker_env(env: dict | None = None) -> object:
    """Remove openviper.tasks from sys.modules and reimport it.

        Submodules are left in sys.modules so their cached objects are reused.
        Only the top-level package is evicted so the module-level ``if`` block
    runs again under the requested environment.
    """
    modules_to_evict = [k for k in sys.modules if k == "openviper.tasks"]
    for k in modules_to_evict:
        del sys.modules[k]

    with patch.dict("os.environ", env or {}):
        mod = importlib.import_module("openviper.tasks")

    return mod


class TestWorkerEnvBranch:
    """Bootstrap code executed when OPENVIPER_WORKER=1."""

    def test_configure_logging_called_when_worker_env_set(self):
        """configure_worker_logging_from_settings() is called on worker import."""
        mock_configure = MagicMock(return_value=MagicMock())

        with patch("openviper.tasks.log.configure_worker_logging_from_settings", mock_configure):
            _reload_tasks_with_worker_env({"OPENVIPER_WORKER": "1"})

        mock_configure.assert_called_once()

    def test_setup_broker_called_when_worker_env_set(self):
        """setup_broker() is called eagerly on worker import."""
        mock_configure = MagicMock(return_value=MagicMock())
        mock_setup = MagicMock()

        with (
            patch("openviper.tasks.log.configure_worker_logging_from_settings", mock_configure),
            patch("openviper.tasks.broker.setup_broker", mock_setup),
        ):
            _reload_tasks_with_worker_env({"OPENVIPER_WORKER": "1"})

        mock_setup.assert_called_once()

    def test_warning_logged_when_setup_broker_raises(self):
        """Exception from setup_broker is caught and a warning is emitted."""
        mock_configure = MagicMock(return_value=MagicMock())
        mock_setup = MagicMock(side_effect=RuntimeError("broker unavailable"))

        with (
            patch("openviper.tasks.log.configure_worker_logging_from_settings", mock_configure),
            patch("openviper.tasks.broker.setup_broker", mock_setup),
            patch("logging.Logger.warning") as mock_warning,
        ):
            _reload_tasks_with_worker_env({"OPENVIPER_WORKER": "1"})

        # The warning must mention the failure
        assert mock_warning.call_count >= 1
        warning_args = " ".join(str(a) for call in mock_warning.call_args_list for a in call[0])
        assert "broker" in warning_args.lower() or "failed" in warning_args.lower()

    def test_worker_env_block_skipped_without_env_var(self):
        """When OPENVIPER_WORKER is not set, configure_logging is NOT called."""
        mock_configure = MagicMock(return_value=MagicMock())

        # Ensure the variable is absent
        with (
            patch("openviper.tasks.log.configure_worker_logging_from_settings", mock_configure),
            patch.dict("os.environ", {}, clear=False),
        ):
            original = os.environ.pop("OPENVIPER_WORKER", None)
            try:
                _reload_tasks_with_worker_env()
            finally:
                if original is not None:
                    os.environ["OPENVIPER_WORKER"] = original

        mock_configure.assert_not_called()
