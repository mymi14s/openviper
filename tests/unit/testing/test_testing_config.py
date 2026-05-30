"""Tests for OpenViper testing configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from openviper.testing.settings import OpenViperTestingConfigError, load_testing_config


class Config:
    def __init__(self, rootpath: Path) -> None:
        self.rootpath = rootpath


def test_load_testing_config_reads_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.openviper.testing]
app = "sample.main:app"
database_url = "sqlite+aiosqlite:///:memory:"
database_isolation = "in_memory"
""",
        encoding="utf-8",
    )

    config = load_testing_config(Config(tmp_path))

    assert config.app == "sample.main:app"
    assert config.database_isolation == "in_memory"


def test_load_testing_config_requires_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENVIPER_TEST_APP", raising=False)

    with pytest.raises(OpenViperTestingConfigError, match="requires"):
        load_testing_config(Config(tmp_path))
