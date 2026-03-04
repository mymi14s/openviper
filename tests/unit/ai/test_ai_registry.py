"""Tests for openviper.ai.registry — ProviderRegistry rewrite.

Covers:
- ``ProviderConfig`` frozen dataclass
- ``ProviderRegistry`` CRUD, locking, and settings load
- ``_resolve_provider_class`` helper
- ``_LegacyAIRegistry`` deprecation shim via ``ai_registry``
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pytest

from openviper.ai.base import AIProvider
from openviper.ai.registry import (
    ProviderConfig,
    ProviderRegistry,
    _LegacyAIRegistry,
    _resolve_provider_class,
    ai_registry,
    provider_registry,
)
from openviper.exceptions import ModelCollisionError, ModelNotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockProvider(AIProvider):
    """Minimal AIProvider stub for registry tests."""

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self._models: list[str] = cfg.get("models", ["mock-v1"])
        self._name = cfg.get("name", "mock")

    def supported_models(self) -> list[str]:
        return list(self._models)

    def provider_name(self) -> str:
        return self._name

    async def generate(self, *args, **kwargs):
        return "mock"

    default_model: str = "mock-v1"


@pytest.fixture(autouse=True)
def isolated_registry():
    """Each test gets a fresh registry and the global is reset afterwards."""
    reg = ProviderRegistry()
    yield reg
    # Reset global singleton so other tests (and the global provider_registry)
    # are unaffected.
    provider_registry.reset()


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


def test_provider_config_defaults():
    cfg = ProviderConfig(provider_type="openai")
    assert cfg.provider_type == "openai"
    assert cfg.api_key == ""
    assert cfg.model == ""
    assert cfg.models == ()
    assert cfg.base_url == ""
    assert isinstance(cfg.extra, dict)


def test_provider_config_is_frozen():
    cfg = ProviderConfig(provider_type="openai", api_key="sk-test")
    import dataclasses

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cfg.api_key = "changed"  # type: ignore[misc]


def test_provider_config_stores_values():
    cfg = ProviderConfig(
        provider_type="anthropic",
        api_key="ak-123",
        model="claude-3",
        models=("claude-3-sonnet", "claude-3-opus"),
        base_url="https://api.anthropic.com",
        extra={"timeout": 30},
    )
    assert cfg.provider_type == "anthropic"
    assert cfg.api_key == "ak-123"
    assert cfg.models == ("claude-3-sonnet", "claude-3-opus")
    assert cfg.extra == {"timeout": 30}


# ---------------------------------------------------------------------------
# ProviderRegistry — register_provider
# ---------------------------------------------------------------------------


def test_register_and_get_by_model(isolated_registry):
    reg = isolated_registry
    provider = MockProvider({"models": ["gpt-4o"]})
    reg.register_provider(provider)
    assert reg.get_by_model("gpt-4o") is provider


def test_register_multiple_models(isolated_registry):
    reg = isolated_registry
    provider = MockProvider({"models": ["m1", "m2", "m3"]})
    reg.register_provider(provider)
    assert reg.get_by_model("m1") is provider
    assert reg.get_by_model("m2") is provider
    assert reg.get_by_model("m3") is provider


def test_get_by_model_raises_model_not_found(isolated_registry):
    reg = isolated_registry
    reg._loaded = True  # skip settings load
    with pytest.raises(ModelNotFoundError):
        reg.get_by_model("nonexistent-model")


def test_register_override_logs_warning(isolated_registry, caplog):
    import logging

    reg = isolated_registry
    p1 = MockProvider({"models": ["model-x"], "name": "provider-a"})
    p2 = MockProvider({"models": ["model-x"], "name": "provider-b"})
    reg.register_provider(p1)
    with caplog.at_level(logging.WARNING, logger="openviper.ai"):
        reg.register_provider(p2)  # override allowed by default
    assert reg.get_by_model("model-x") is p2
    assert any("overridden" in r.message for r in caplog.records)


def test_register_no_override_raises_collision(isolated_registry):
    reg = isolated_registry
    p1 = MockProvider({"models": ["model-x"], "name": "p1"})
    p2 = MockProvider({"models": ["model-x"], "name": "p2"})
    reg.register_provider(p1)
    with pytest.raises(ModelCollisionError):
        reg.register_provider(p2, allow_override=False)


# ---------------------------------------------------------------------------
# ProviderRegistry — list_models / list_provider_names
# ---------------------------------------------------------------------------


def test_list_models(isolated_registry):
    reg = isolated_registry
    reg._loaded = True
    p1 = MockProvider({"models": ["b-model", "a-model"]})
    reg.register_provider(p1)
    assert reg.list_models() == ["a-model", "b-model"]  # sorted


def test_list_provider_names(isolated_registry):
    reg = isolated_registry
    reg._loaded = True
    p1 = MockProvider({"models": ["m1"], "name": "prov-a"})
    p2 = MockProvider({"models": ["m2"], "name": "prov-b"})
    reg.register_provider(p1)
    reg.register_provider(p2)
    names = reg.list_provider_names()
    assert sorted(names) == ["prov-a", "prov-b"]


# ---------------------------------------------------------------------------
# ProviderRegistry — reset
# ---------------------------------------------------------------------------


def test_reset_clears_models(isolated_registry):
    reg = isolated_registry
    reg._loaded = True
    reg.register_provider(MockProvider({"models": ["m1"]}))
    reg.reset()
    assert reg._loaded is False
    assert reg._model_map == {}


# ---------------------------------------------------------------------------
# ProviderRegistry — _load_from_settings / _ensure_loaded
# ---------------------------------------------------------------------------


def test_ensure_loaded_runs_exactly_once(isolated_registry):
    reg = isolated_registry
    load_calls = []

    with patch.object(ProviderRegistry, "_load_from_settings") as mock_load:
        mock_load.side_effect = lambda: load_calls.append(1)
        reg._ensure_loaded()
        reg._ensure_loaded()  # second call: already loaded, should not run again

    assert len(load_calls) == 1


def test_load_from_settings_registers_provider(isolated_registry):
    reg = isolated_registry
    mock_cls = MagicMock(return_value=MockProvider({"models": ["test-model"]}))
    cfg = {"test-provider": {"provider": "openai", "api_key": "sk-x", "model": "test-model"}}
    with patch("openviper.ai.registry.settings") as mock_settings:
        mock_settings.AI_PROVIDERS = cfg
        with patch("openviper.ai.registry._resolve_provider_class", return_value=mock_cls):
            reg._load_from_settings()
    assert "test-model" in reg.list_models()


def test_load_from_settings_skips_unknown_provider(isolated_registry):
    reg = isolated_registry
    cfg = {"x": {"provider": "nonexistent_xyz"}}
    with patch("openviper.ai.registry.settings") as mock_settings:
        mock_settings.AI_PROVIDERS = cfg
        reg._load_from_settings()
    assert reg.list_models() == []


def test_load_from_settings_empty_providers(isolated_registry):
    reg = isolated_registry
    with patch("openviper.ai.registry.settings") as mock_settings:
        mock_settings.AI_PROVIDERS = {}
        reg._load_from_settings()
    reg._loaded = True  # prevent auto-reload
    assert reg.list_models() == []


def test_load_from_settings_handles_exception_silently(isolated_registry):
    reg = isolated_registry
    with patch("openviper.ai.registry.settings") as mock_settings:
        # Make settings.AI_PROVIDERS.items() raise — the loader must swallow it.
        mock_settings.AI_PROVIDERS = MagicMock(items=MagicMock(side_effect=RuntimeError("boom")))
        # Should not propagate
        reg._load_from_settings()


# ---------------------------------------------------------------------------
# _resolve_provider_class
# ---------------------------------------------------------------------------


def test_resolve_provider_class_unknown_returns_none():
    assert _resolve_provider_class("totally_unknown_xyz") is None


def test_resolve_provider_class_empty_returns_none():
    assert _resolve_provider_class("") is None


def test_resolve_provider_class_import_error_returns_none():
    with patch("importlib.import_module", side_effect=ImportError("no module")):
        result = _resolve_provider_class("openai")
    assert result is None


def test_resolve_provider_class_attribute_error_returns_none():
    mock_module = MagicMock(spec=[])
    with patch("importlib.import_module", return_value=mock_module):
        result = _resolve_provider_class("openai")
    assert result is None


def test_resolve_provider_class_openai():
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.OpenAIProvider = mock_cls
    with patch("importlib.import_module", return_value=mock_module) as mock_import:
        result = _resolve_provider_class("openai")
    mock_import.assert_called_once_with("openviper.ai.providers.openai_provider")
    assert result is mock_cls


def test_resolve_provider_class_anthropic():
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.AnthropicProvider = mock_cls
    with patch("importlib.import_module", return_value=mock_module):
        assert _resolve_provider_class("anthropic") is mock_cls


def test_resolve_provider_class_gemini():
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.GeminiProvider = mock_cls
    with patch("importlib.import_module", return_value=mock_module):
        assert _resolve_provider_class("gemini") is mock_cls


def test_resolve_provider_class_ollama():
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.OllamaProvider = mock_cls
    with patch("importlib.import_module", return_value=mock_module):
        assert _resolve_provider_class("ollama") is mock_cls


def test_resolve_provider_class_grok():
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.GrokProvider = mock_cls
    with patch("importlib.import_module", return_value=mock_module):
        assert _resolve_provider_class("grok") is mock_cls


# ---------------------------------------------------------------------------
# _LegacyAIRegistry deprecation shim
# ---------------------------------------------------------------------------


def test_ai_registry_is_legacy_shim():
    assert isinstance(ai_registry, _LegacyAIRegistry)


def test_ai_registry_access_triggers_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = ai_registry.list_models  # attribute access triggers warning
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any("provider_registry" in str(w.message) for w in caught)


def test_ai_registry_delegates_attribute_to_provider_registry(isolated_registry):
    """Accessing ai_registry.<attr> forwards to provider_registry.<attr>."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        fn = ai_registry.list_models
    # The returned callable should be the same as provider_registry.list_models
    assert fn == provider_registry.list_models


# ---------------------------------------------------------------------------
# register_provider — default_model fallback (line 152)
# ---------------------------------------------------------------------------


def test_register_provider_uses_default_model_when_no_supported_models(isolated_registry):
    """Line 152: when provider.supported_models() returns [] but default_model set,
    use default_model as the registry key."""
    reg = isolated_registry

    class _EmptyModelsProvider(AIProvider):
        default_model = "my-fallback-model"

        def supported_models(self):
            return []

        def provider_name(self):
            return "empty-test"

        async def generate(self, *a, **kw):
            return "x"

    p = _EmptyModelsProvider({"model": "my-fallback-model"})
    reg.register_provider(p)
    reg._loaded = True
    assert "my-fallback-model" in reg.list_models()
    assert reg.get_by_model("my-fallback-model") is p


# ---------------------------------------------------------------------------
# register_from_module (lines 186-207)
# ---------------------------------------------------------------------------


def test_register_from_module_via_get_providers(isolated_registry, tmp_path):
    """Lines 186-207: module with get_providers() function is registered."""
    import importlib
    import sys
    import types

    reg = isolated_registry
    provider = MockProvider({"models": ["from-module-model"]})

    fake_module = types.ModuleType("fake_provider_module")
    fake_module.get_providers = lambda: [provider]

    sys.modules["fake_provider_module"] = fake_module
    try:
        count = reg.register_from_module("fake_provider_module")
    finally:
        del sys.modules["fake_provider_module"]

    assert count == 1
    reg._loaded = True
    assert "from-module-model" in reg.list_models()


def test_register_from_module_via_providers_list(isolated_registry):
    """register_from_module uses PROVIDERS variable when get_providers absent."""
    import sys
    import types

    reg = isolated_registry
    provider = MockProvider({"models": ["providers-var-model"]})

    fake_module = types.ModuleType("fake_prov_list_module")
    fake_module.PROVIDERS = [provider]  # type: ignore[attr-defined]

    sys.modules["fake_prov_list_module"] = fake_module
    try:
        count = reg.register_from_module("fake_prov_list_module")
    finally:
        del sys.modules["fake_prov_list_module"]

    assert count == 1


def test_register_from_module_ignores_non_provider_instances(isolated_registry):
    """Non-AIProvider items in get_providers() return value are silently skipped."""
    import sys
    import types

    reg = isolated_registry
    fake_module = types.ModuleType("fake_non_provider_module")
    fake_module.get_providers = lambda: ["not a provider", 42, None]  # type: ignore[attr-defined]

    sys.modules["fake_non_provider_module"] = fake_module
    try:
        count = reg.register_from_module("fake_non_provider_module")
    finally:
        del sys.modules["fake_non_provider_module"]

    assert count == 0


# ---------------------------------------------------------------------------
# load_plugins (lines 231-270)
# ---------------------------------------------------------------------------


def test_load_plugins_not_a_directory(isolated_registry, caplog):
    """load_plugins with non-existent directory returns 0 and logs a warning."""
    import logging

    reg = isolated_registry
    with caplog.at_level(logging.WARNING, logger="openviper.ai"):
        result = reg.load_plugins("/nonexistent/path/that/does/not/exist")
    assert result == 0


def test_load_plugins_registers_providers_from_py_files(isolated_registry, tmp_path):
    """load_plugins processes .py files (non-underscore) in the directory."""
    # Create a plugin directory with one valid .py file (no actual providers)
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "my_plugin.py"
    plugin_file.write_text("# placeholder — no providers defined\n")

    # load_plugins should run without raising regardless of whether the module
    # has registerable providers; result is an integer count
    result = isolated_registry.load_plugins(str(plugin_dir))
    assert isinstance(result, int)
    assert result >= 0


def test_load_plugins_skips_files_starting_with_underscore(isolated_registry, tmp_path):
    """Files starting with _ are not imported."""
    plugin_dir = tmp_path / "skip_plugins"
    plugin_dir.mkdir()
    (plugin_dir / "_private.py").write_text("# private\n")

    result = isolated_registry.load_plugins(str(plugin_dir))
    assert result == 0  # _private.py was skipped


# ---------------------------------------------------------------------------
# discover_entrypoints (lines 296-328)
# ---------------------------------------------------------------------------


def test_discover_entrypoints_returns_zero_when_none(isolated_registry):
    """No entry-points for the group → returns 0."""
    with patch("importlib.metadata.entry_points", return_value=[]):
        result = isolated_registry.discover_entrypoints()
    assert result == 0


def test_discover_entrypoints_registers_providers(isolated_registry):
    """Entry-point factory returning a provider list causes registration."""
    provider = MockProvider({"models": ["ep-model"]})

    mock_ep = MagicMock()
    mock_ep.name = "my_ep"
    mock_ep.load.return_value = lambda: [provider]

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        count = isolated_registry.discover_entrypoints()

    assert count == 1
    isolated_registry._loaded = True
    assert "ep-model" in isolated_registry.list_models()


def test_discover_entrypoints_logs_warning_on_failure(isolated_registry, caplog):
    """Exception from entry-point factory is caught and logged."""
    import logging

    mock_ep = MagicMock()
    mock_ep.name = "bad_ep"
    mock_ep.load.side_effect = RuntimeError("entrypoint broken")

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        with caplog.at_level(logging.WARNING, logger="openviper.ai"):
            count = isolated_registry.discover_entrypoints()

    assert count == 0
    assert "bad_ep" in caplog.text or "failed" in caplog.text.lower()


# ---------------------------------------------------------------------------
# _load_from_settings — type inference from provider name (lines 393-396)
# ---------------------------------------------------------------------------


def test_load_from_settings_infers_provider_type_from_name(isolated_registry):
    """Lines 393-396: provider type inferred from name if 'provider' key absent."""
    mock_cls = MagicMock(return_value=MockProvider({"models": ["inferred-model"]}))
    cfg = {"my-openai-provider": {"api_key": "sk-x"}}  # no 'provider' key but name has 'openai'
    with patch("openviper.ai.registry.settings") as ms:
        ms.AI_PROVIDERS = cfg
        with patch("openviper.ai.registry._resolve_provider_class", return_value=mock_cls):
            isolated_registry._load_from_settings()

    isolated_registry._loaded = True
    assert "inferred-model" in isolated_registry.list_models()


def test_load_from_settings_logs_warning_on_init_exception(isolated_registry, caplog):
    """Lines 407-408: exception from provider constructor is logged as warning."""
    import logging

    class _BrokenProvider:
        def __init__(self, cfg):
            raise RuntimeError("init failed!")

    cfg = {"my-broken": {"provider": "openai"}}
    with patch("openviper.ai.registry.settings") as ms:
        ms.AI_PROVIDERS = cfg
        with patch("openviper.ai.registry._resolve_provider_class", return_value=_BrokenProvider):
            with caplog.at_level(logging.WARNING, logger="openviper.ai"):
                isolated_registry._load_from_settings()

    assert "init failed!" in caplog.text or "my-broken" in caplog.text
