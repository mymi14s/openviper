"""Unit tests for openviper.__init__ (package entrypoint)."""

from unittest.mock import patch

import pytest

import openviper
from openviper.conf.settings import settings as _settings


def test_version_and_all_exports():
    assert hasattr(openviper, "__version__")
    assert isinstance(openviper.__version__, str)
    for name in openviper.__all__:
        assert hasattr(openviper, name)


def test___all___is_complete():
    # All exported names should be present in the module
    for name in openviper.__all__:
        assert hasattr(openviper, name)


def test_setup_calls_settings_setup():
    """openviper.setup(force=True) should always run _setup and leave settings configured."""
    # setup(force=True) re-runs _setup unconditionally.
    # We verify the observable outcome: settings remain configured with a live instance.
    openviper.setup(force=True)
    assert _settings._configured is True
    assert _settings._instance is not None


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
