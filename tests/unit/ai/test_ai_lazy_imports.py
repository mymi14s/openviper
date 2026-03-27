"""Tests for lazy re-export modules under openviper.ai.

These modules exist mainly to keep optional SDK imports from being required
at import time.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

import openviper.ai as ai_pkg
import openviper.ai.providers as providers_pkg


class TestAIPackageLazyGetattr:
    def test_getattr_imports_provider_module(self) -> None:
        mod = types.SimpleNamespace(GeminiProvider=object())
        with patch("importlib.import_module", return_value=mod) as mock_import:
            assert ai_pkg.__getattr__("GeminiProvider") is mod.GeminiProvider
        mock_import.assert_called_once_with("openviper.ai.providers.gemini_provider")

    def test_getattr_unknown_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            ai_pkg.__getattr__("DoesNotExist")


class TestProvidersPackageLazyGetattr:
    def test_getattr_imports_provider_module(self) -> None:
        mod = types.SimpleNamespace(GrokProvider=object())
        with patch("importlib.import_module", return_value=mod) as mock_import:
            assert providers_pkg.__getattr__("GrokProvider") is mod.GrokProvider
        mock_import.assert_called_once_with("openviper.ai.providers.grok_provider")

    def test_getattr_unknown_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            providers_pkg.__getattr__("DoesNotExist")
