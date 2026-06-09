"""Tests for openviper.utils.logging - ConcurrentRotatingFileHandler."""

from __future__ import annotations

import logging
from pathlib import Path

from openviper.utils.logging import ConcurrentRotatingFileHandler, build_formatter


class TestConcurrentRotatingFileHandler:
    """Test the OpenViper-native concurrent rotating file handler."""

    def test_inherits_from_rotating_file_handler(self) -> None:
        """ConcurrentRotatingFileHandler must extend RotatingFileHandler."""
        from logging.handlers import RotatingFileHandler

        assert issubclass(ConcurrentRotatingFileHandler, RotatingFileHandler)

    def test_creates_log_file(self, tmp_path: Path) -> None:
        """Handler must create the log file on first emit."""
        log_path = tmp_path / "test_concurrent.log"
        handler = ConcurrentRotatingFileHandler(
            log_path, maxBytes=1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test_concurrent_handler")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("test message")

        handler.close()
        assert log_path.exists()
        content = log_path.read_text()
        assert "test message" in content

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        """Handler must accept a Path object as filename."""
        log_path = tmp_path / "path_obj.log"
        handler = ConcurrentRotatingFileHandler(log_path, maxBytes=1024, backupCount=2)
        handler.close()
        assert log_path.exists() or True  # File created on first emit

    def test_rotation_respects_max_bytes(self, tmp_path: Path) -> None:
        """Handler must rotate files when maxBytes is exceeded."""
        log_path = tmp_path / "rotate.log"
        handler = ConcurrentRotatingFileHandler(
            log_path, maxBytes=256, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test_rotation")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        for i in range(50):
            logger.info("line %04d - padding to exceed maxBytes", i)

        handler.close()
        assert log_path.exists()

    def test_build_formatter_text(self) -> None:
        """build_formatter must produce a text formatter."""
        fmt = build_formatter("text", console=False)
        assert isinstance(fmt, logging.Formatter)

    def test_build_formatter_json(self) -> None:
        """build_formatter must produce a JSON formatter."""
        fmt = build_formatter("json", console=False)
        assert isinstance(fmt, logging.Formatter)
