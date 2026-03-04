"""Coverage for openviper/tasks/__init__.py — OPENVIPER_WORKER conditional block."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import MagicMock, patch


def _ensure_broker_loaded():
    """Make sure openviper.tasks.broker is in sys.modules before patching."""
    if "openviper.tasks.broker" not in sys.modules:
        import openviper.tasks.broker  # noqa: F401


def _reload_tasks_module():
    """Remove openviper.tasks from sys.modules and re-import it."""
    sys.modules.pop("openviper.tasks", None)
    return importlib.import_module("openviper.tasks")


def _restore_tasks_module(original_module):
    """Restore the original module in sys.modules AND the parent package attribute."""
    import openviper as _ov_pkg

    sys.modules.pop("openviper.tasks", None)
    if original_module is not None:
        sys.modules["openviper.tasks"] = original_module
        _ov_pkg.tasks = original_module


# ---------------------------------------------------------------------------
# Lines 75-85: OPENVIPER_WORKER env var block — success path
# ---------------------------------------------------------------------------


def test_openviper_worker_env_triggers_broker_setup():
    """Lines 75-85: OPENVIPER_WORKER=1 triggers configure logging + broker setup."""
    _ensure_broker_loaded()
    original_module = sys.modules.get("openviper.tasks")
    original_env = os.environ.get("OPENVIPER_WORKER")
    os.environ["OPENVIPER_WORKER"] = "1"

    mock_setup = MagicMock()

    try:
        with patch.object(sys.modules["openviper.tasks.broker"], "setup_broker", mock_setup):
            _reload_tasks_module()

        # setup_broker should have been called via the OPENVIPER_WORKER block
        mock_setup.assert_called_once()
    finally:
        if original_env is None:
            os.environ.pop("OPENVIPER_WORKER", None)
        else:
            os.environ["OPENVIPER_WORKER"] = original_env
        _restore_tasks_module(original_module)


# ---------------------------------------------------------------------------
# Lines 86-89: OPENVIPER_WORKER env var block — exception path
# ---------------------------------------------------------------------------


def test_openviper_worker_env_broker_setup_exception_is_swallowed():
    """Lines 86-89: exception from setup_broker() is caught as warning, not raised."""
    _ensure_broker_loaded()
    original_module = sys.modules.get("openviper.tasks")
    original_env = os.environ.get("OPENVIPER_WORKER")
    os.environ["OPENVIPER_WORKER"] = "1"

    try:
        with patch.object(
            sys.modules["openviper.tasks.broker"],
            "setup_broker",
            side_effect=RuntimeError("broker unavailable"),
        ):
            # Must NOT raise — exception is caught by the except block
            _reload_tasks_module()
    finally:
        if original_env is None:
            os.environ.pop("OPENVIPER_WORKER", None)
        else:
            os.environ["OPENVIPER_WORKER"] = original_env
        _restore_tasks_module(original_module)


# ---------------------------------------------------------------------------
# Lines 75 (false branch): OPENVIPER_WORKER NOT set → block is skipped
# ---------------------------------------------------------------------------


def test_no_openviper_worker_env_skips_broker_setup():
    """Line 75: without OPENVIPER_WORKER, the conditional block is NOT entered."""
    _ensure_broker_loaded()
    original_module = sys.modules.get("openviper.tasks")
    original_env = os.environ.pop("OPENVIPER_WORKER", None)

    mock_setup = MagicMock()

    try:
        with patch.object(sys.modules["openviper.tasks.broker"], "setup_broker", mock_setup):
            _reload_tasks_module()

        # Without OPENVIPER_WORKER, setup_broker should NOT have been called
        mock_setup.assert_not_called()
    finally:
        if original_env is not None:
            os.environ["OPENVIPER_WORKER"] = original_env
        _restore_tasks_module(original_module)
