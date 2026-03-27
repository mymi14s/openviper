"""Additional branch tests for openviper.ai.registry.

Covers plugin loading, entry-point discovery, and settings-driven initialisation.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest

import openviper.ai.registry as registry_module
from openviper.ai.base import AIProvider
from openviper.ai.registry import ProviderRegistry


class _P(AIProvider):
    name = "p"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config or {})

    async def generate(self, prompt: str, **kwargs) -> str:
        return "ok"


class TestLoadPlugins:
    def test_non_directory_returns_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = ProviderRegistry()
        reg._loaded = True
        caplog.set_level("WARNING")
        assert reg.load_plugins("/path/does/not/exist") == 0

    def test_load_plugins_inserts_and_removes_sys_path(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "ai_plugins"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        (plugin_dir / "a.py").write_text("# plugin")
        (plugin_dir / "b.py").write_text("# plugin")
        (plugin_dir / "_skip.py").write_text("# skip")

        reg = ProviderRegistry()
        reg._loaded = True

        original_sys_path = list(sys.path)

        def side_effect(module_path: str, *, allow_override: bool = True) -> int:
            if module_path.endswith(".b"):
                raise ImportError("boom")
            return 2

        with patch.object(
            ProviderRegistry, "register_from_module", side_effect=side_effect
        ) as mock_rfm:
            total = reg.load_plugins(str(plugin_dir))

        assert total == 2
        called = {c.args[0] for c in mock_rfm.call_args_list}
        assert called == {"ai_plugins.a", "ai_plugins.b"}
        assert list(sys.path) == original_sys_path


class TestDiscoverEntrypoints:
    def test_discovers_valid_entrypoints_and_skips_errors(self) -> None:
        reg = ProviderRegistry()
        reg._loaded = True

        class _EP:
            def __init__(self, name: str, factory):
                self.name = name
                self._factory = factory

            def load(self):
                return self._factory

        def factory_one():
            return _P({"model": "m1"})

        def factory_list():
            return [_P({"model": "m2"}), object()]

        def factory_raises():
            raise RuntimeError("bad")

        eps = [_EP("one", factory_one), _EP("list", factory_list), _EP("bad", factory_raises)]

        with patch("openviper.ai.registry.entry_points", return_value=eps):
            count = reg.discover_entrypoints()

        assert count == 2
        assert reg.get_by_model("m1") is not None
        assert reg.get_by_model("m2") is not None


class TestLoadFromSettings:
    def test_loads_providers_from_settings_and_handles_init_errors(self) -> None:
        reg = ProviderRegistry()

        class OkProvider(_P):
            pass

        class BadProvider(_P):
            def __init__(self, config: dict | None = None) -> None:
                raise RuntimeError("init fail")

        ai_providers = {
            "openai-main": {"api_key": "k", "model": "m"},  # type inferred from name
            "custom": {"provider": "custom", "model": "x"},
            "bad": {"provider": "bad", "model": "y"},
        }

        def resolver(provider_type: str):
            if provider_type == "openai":
                return OkProvider
            if provider_type == "custom":
                return OkProvider
            if provider_type == "bad":
                return BadProvider
            return None

        with (
            patch("openviper.ai.registry.settings") as mock_settings,
            patch("openviper.ai.registry._resolve_provider_class", side_effect=resolver),
            patch("openviper.ai.registry.logger") as mock_logger,
        ):
            mock_settings.AI_PROVIDERS = ai_providers
            reg._load_from_settings()

        assert reg.get_by_model("m") is not None
        assert reg.get_by_model("x") is not None
        assert mock_logger.warning.called

    def test_ensure_loaded_calls_load_once(self) -> None:
        reg = ProviderRegistry()
        with patch.object(ProviderRegistry, "_load_from_settings") as mock_load:
            reg._ensure_loaded()
            reg._ensure_loaded()
        mock_load.assert_called_once()


class TestResolveProviderClassDynamic:
    def test_dynamic_import_attribute_error_returns_none(self) -> None:
        registry_module._CACHE_INITIALIZED = True
        registry_module._PROVIDER_CLASS_CACHE.clear()

        with patch(
            "openviper.ai.registry.importlib.import_module", return_value=types.SimpleNamespace()
        ):
            assert registry_module._resolve_provider_class("openai") is None

    def test_unknown_provider_returns_none(self) -> None:
        registry_module._CACHE_INITIALIZED = True
        registry_module._PROVIDER_CLASS_CACHE.clear()
        assert registry_module._resolve_provider_class("does-not-exist") is None

    def test_returns_cached_value(self) -> None:
        registry_module._CACHE_INITIALIZED = True
        registry_module._PROVIDER_CLASS_CACHE["x"] = None
        assert registry_module._resolve_provider_class("x") is None
