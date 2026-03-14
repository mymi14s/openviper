"""Additional branch tests for openviper.db.events."""

from __future__ import annotations

from unittest.mock import patch

import openviper.db.events as events_module
from openviper.db.events import _UNSET, get_dispatcher, reset_dispatcher


def test_get_dispatcher_double_check_inside_lock_branch():
    reset_dispatcher()

    class MockLock:
        def __enter__(self):
            events_module._dispatcher_cache = None
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch.object(events_module, "_init_lock", MockLock()):
        with patch.object(events_module, "_build_dispatcher") as mock_build:
            result = get_dispatcher()
            assert result is None
            mock_build.assert_not_called()

    events_module._dispatcher_cache = _UNSET
