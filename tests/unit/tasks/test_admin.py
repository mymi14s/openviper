"""Tests for :mod:`openviper.tasks.admin`.

This module is tiny but is included in the coverage target (``--cov=openviper/tasks``).
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from openviper.tasks.models import TaskResult


def test_task_result_admin_is_registered_and_configured() -> None:
    dummy_admin = ModuleType("openviper.admin")

    class DummyModelAdmin:  # pragma: no cover
        pass

    register_spy = MagicMock()

    def register(model):
        def decorator(cls):
            register_spy(model, cls)
            return cls

        return decorator

    dummy_admin.ModelAdmin = DummyModelAdmin
    dummy_admin.register = register

    with patch.dict(sys.modules, {"openviper.admin": dummy_admin}):
        sys.modules.pop("openviper.tasks.admin", None)
        mod = importlib.import_module("openviper.tasks.admin")

    assert mod.TaskResultAdmin.list_display_styles["status"] == "status_badge"
    assert issubclass(mod.TaskResultAdmin, DummyModelAdmin)
    register_spy.assert_called_once()
    assert register_spy.call_args[0][0] is TaskResult
