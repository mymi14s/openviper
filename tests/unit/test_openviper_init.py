"""Unit tests for openviper.__init__ (package entrypoint)."""

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

import openviper
from openviper.conf.settings import settings as settings


def test_version_and_all_exports():
    assert hasattr(openviper, "__version__")
    assert isinstance(openviper.__version__, str)
    for name in openviper.__all__:
        assert hasattr(openviper, name)


def test___all___is_complete():
    # All exported names should be present in the module
    for name in openviper.__all__:
        assert hasattr(openviper, name)


def test_setup_callssettings_setup():
    """openviper.setup(force=True) should always run setup and leave settings configured."""
    openviper.setup(force=True)
    assert settings.configured is True
    assert settings.instance is not None


def test_getattr_lazy_loads_subpackage():
    # Patch importlib to simulate subpackage
    with patch("importlib.import_module", return_value="mocked_module") as mock_import:
        result = openviper.__getattr__("ai")
        assert result == "mocked_module"
        assert hasattr(openviper, "ai")
        assert openviper.ai == "mocked_module"
        mock_import.assert_called_once_with("openviper.ai")


def test_getattr_raises_for_unknown():
    with pytest.raises(AttributeError) as exc:
        openviper.__getattr__("not_a_real_subpackage")
    assert "has no attribute" in str(exc.value)


def test_cli_import_does_not_load_projectsettings() -> None:
    env = os.environ.copy()
    env["OPENVIPER_SETTINGS_MODULE"] = "missing_project.settings"

    result = subprocess.run(
        [sys.executable, "-c", "from openviper.cli import cli; print(cli.name)"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "cli"
