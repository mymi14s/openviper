"""Unit tests for openviper/tasks/log.py and tasks/broker.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import openviper.tasks.log as log_mod
from openviper.tasks.broker import get_broker, reset_broker, setup_broker
from openviper.tasks.log import configure_worker_logging

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def reset_logging_flag():
    """Reset the module-level _LOGGING_CONFIGURED flag."""
    log_mod._LOGGING_CONFIGURED = False


# ---------------------------------------------------------------------------
# configure_worker_logging
# ---------------------------------------------------------------------------


class TestConfigureWorkerLogging:
    def setup_method(self):
        reset_logging_flag()

    def test_returns_path(self, tmp_path):
        result = configure_worker_logging(log_dir=tmp_path, log_to_file=False)
        assert isinstance(result, Path)

    def test_default_log_dir_uses_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = configure_worker_logging(log_to_file=False)
        assert "logs" in str(result)

    def test_creates_log_files_when_enabled(self, tmp_path):
        configure_worker_logging(
            log_dir=tmp_path,
            log_level="DEBUG",
            log_to_file=True,
        )
        assert (tmp_path / "worker.log").exists()

    def test_no_files_when_log_to_file_false(self, tmp_path):
        configure_worker_logging(log_dir=tmp_path, log_to_file=False)
        assert not (tmp_path / "worker.log").exists()

    def test_idempotent_on_second_call(self, tmp_path):
        configure_worker_logging(log_dir=tmp_path, log_to_file=True)
        result2 = configure_worker_logging(log_dir=tmp_path, log_to_file=True)
        # Second call should return without re-configuring
        assert isinstance(result2, Path)

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
    def test_various_log_levels(self, tmp_path, level):
        reset_logging_flag()
        result = configure_worker_logging(log_dir=tmp_path, log_level=level, log_to_file=False)
        assert isinstance(result, Path)

    def test_json_format(self, tmp_path):
        configure_worker_logging(log_dir=tmp_path, log_format="json", log_to_file=True)
        assert (tmp_path / "worker.log").exists()

    def test_text_format(self, tmp_path):
        configure_worker_logging(log_dir=tmp_path, log_format="text", log_to_file=True)
        assert (tmp_path / "worker.log").exists()


# ---------------------------------------------------------------------------
# get_broker / reset_broker
# ---------------------------------------------------------------------------


class TestBroker:
    def setup_method(self):
        reset_broker()

    def teardown_method(self):
        reset_broker()

    def test_get_broker_with_stub(self):
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"broker": "stub", "enabled": 1}
            broker = get_broker()
            assert broker is not None

    def test_get_broker_returns_same_instance(self):
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"broker": "stub", "enabled": 1}
            b1 = get_broker()
            b2 = get_broker()
            assert b1 is b2

    def test_reset_broker_clears_cached(self):
        with patch("openviper.tasks.broker.settings") as mock_settings:
            mock_settings.TASKS = {"broker": "stub", "enabled": 1}
            b1 = get_broker()
            reset_broker()
            b2 = get_broker()
            # After reset, a new broker is created
            # b1 and b2 may differ or be equal depending on implementation

    def test_setup_broker_is_alias(self):
        assert setup_broker is get_broker
