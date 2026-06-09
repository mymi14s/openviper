"""Tests for openviper.tasks.exceptions."""

from __future__ import annotations

import pytest

from openviper.tasks.exceptions import (
    OpenViperTasksConfigurationError,
    OpenViperTasksError,
    ResultsBackendDisabledError,
)


class TestExceptions:
    """Test task exception hierarchy."""

    def test_configuration_error_is_tasks_error(self) -> None:
        err = OpenViperTasksConfigurationError(["bad config"])
        assert isinstance(err, OpenViperTasksError)

    def test_configuration_error_stores_errors(self) -> None:
        err = OpenViperTasksConfigurationError(["err1", "err2"])
        assert err.errors == ["err1", "err2"]
        assert "err1" in str(err)

    def test_results_backend_disabled_error(self) -> None:
        err = ResultsBackendDisabledError()
        assert isinstance(err, OpenViperTasksError)
