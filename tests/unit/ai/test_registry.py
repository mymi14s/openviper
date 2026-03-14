"""Unit tests for openviper/ai/registry.py — ProviderRegistry."""

from __future__ import annotations

import types
import warnings
from unittest.mock import patch

import pytest

from openviper.ai.base import AIProvider
from openviper.ai.registry import (
    ProviderConfig,
    ProviderRegistry,
    _LegacyAIRegistry,
    provider_registry,
)
from openviper.exceptions import ModelCollisionError, ModelNotFoundError

# ---------------------------------------------------------------------------
# Concrete stub
# ---------------------------------------------------------------------------


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, config: dict | None = None, *, name: str = "fake"):
        super().__init__(config or {})
        self.name = name

    async def generate(self, prompt: str, **kwargs) -> str:
        return "fake"


# ---------------------------------------------------------------------------
# ProviderConfig dataclass
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_frozen(self):
        cfg = ProviderConfig(provider_type="openai", api_key="key")
        with pytest.raises(AttributeError):
            cfg.api_key = "new"  # type: ignore[misc]

    def test_defaults(self):
        cfg = ProviderConfig(provider_type="openai")
        assert cfg.api_key == ""
        assert cfg.model == ""
        assert cfg.models == ()
        assert cfg.base_url == ""
        assert cfg.extra == {}


# ---------------------------------------------------------------------------
# ProviderRegistry — register_provider
# ---------------------------------------------------------------------------


class TestRegisterProvider:
    def setup_method(self):
        self.registry = ProviderRegistry()
        self.registry._loaded = True  # skip settings loading

    def test_register_maps_models(self):
        p = FakeProvider({"models": ["model-a", "model-b"]})
        self.registry.register_provider(p)
        assert self.registry.get_by_model("model-a") is p
        assert self.registry.get_by_model("model-b") is p

    def test_register_fallback_to_default_model(self):
        p = FakeProvider({"model": "solo-model"})
        # supported_models returns ["solo-model"], so it maps directly
        self.registry.register_provider(p)
        assert self.registry.get_by_model("solo-model") is p

    def test_override_allowed_by_default(self):
        p1 = FakeProvider({"model": "shared"}, name="first")
        p2 = FakeProvider({"model": "shared"}, name="second")
        self.registry.register_provider(p1)
        self.registry.register_provider(p2)
        assert self.registry.get_by_model("shared") is p2

    def test_override_disallowed_raises_collision(self):
        p1 = FakeProvider({"model": "shared"}, name="first")
        p2 = FakeProvider({"model": "shared"}, name="second")
        self.registry.register_provider(p1)
        with pytest.raises(ModelCollisionError):
            self.registry.register_provider(p2, allow_override=False)

    def test_same_provider_re_register_no_collision(self):
        p = FakeProvider({"model": "m1"})
        self.registry.register_provider(p)
        self.registry.register_provider(p, allow_override=False)  # same instance, no error


# ---------------------------------------------------------------------------
# ProviderRegistry — get_by_model / list_models / list_provider_names
# ---------------------------------------------------------------------------


class TestRegistryQueries:
    def setup_method(self):
        self.registry = ProviderRegistry()
        self.registry._loaded = True

    def test_get_by_model_raises_model_not_found(self):
        with pytest.raises(ModelNotFoundError):
            self.registry.get_by_model("nonexistent")

    def test_list_models_empty(self):
        assert self.registry.list_models() == []

    def test_list_models_sorted(self):
        self.registry.register_provider(FakeProvider({"models": ["b", "a", "c"]}))
        assert self.registry.list_models() == ["a", "b", "c"]

    def test_list_provider_names(self):
        self.registry.register_provider(FakeProvider({"model": "m1"}, name="alpha"))
        self.registry.register_provider(FakeProvider({"model": "m2"}, name="beta"))
        names = self.registry.list_provider_names()
        assert "alpha" in names
        assert "beta" in names


# ---------------------------------------------------------------------------
# ProviderRegistry — reset
# ---------------------------------------------------------------------------


class TestRegistryReset:
    def test_reset_clears_models(self):
        registry = ProviderRegistry()
        registry._loaded = True
        registry.register_provider(FakeProvider({"model": "m1"}))
        assert registry.list_models() == ["m1"]
        registry.reset()
        # After reset, _loaded is False — set it back to skip _load_from_settings
        registry._loaded = True
        assert registry.list_models() == []


# ---------------------------------------------------------------------------
# ProviderRegistry — register_from_module
# ---------------------------------------------------------------------------


class TestRegisterFromModule:
    def setup_method(self):
        self.registry = ProviderRegistry()
        self.registry._loaded = True

    def test_import_error_propagates(self):
        with pytest.raises(ImportError):
            self.registry.register_from_module("nonexistent.module.path")

    def test_loads_get_providers_callable(self):
        mod = types.ModuleType("fake_mod")
        mod.get_providers = lambda: [FakeProvider({"model": "from-mod"})]  # type: ignore[attr-defined]
        with patch("importlib.import_module", return_value=mod):
            count = self.registry.register_from_module("fake_mod")
        assert count == 1
        assert self.registry.get_by_model("from-mod") is not None

    def test_loads_providers_list(self):
        mod = types.ModuleType("fake_mod")
        mod.PROVIDERS = [FakeProvider({"model": "from-list"})]  # type: ignore[attr-defined]
        with patch("importlib.import_module", return_value=mod):
            count = self.registry.register_from_module("fake_mod")
        assert count == 1

    def test_get_providers_takes_precedence_over_providers(self):
        mod = types.ModuleType("fake_mod")
        mod.get_providers = lambda: [FakeProvider({"model": "from-func"})]  # type: ignore[attr-defined]
        mod.PROVIDERS = [FakeProvider({"model": "from-list"})]  # type: ignore[attr-defined]
        with patch("importlib.import_module", return_value=mod):
            self.registry.register_from_module("fake_mod")
        assert "from-func" in self.registry.list_models()


# ---------------------------------------------------------------------------
# Legacy shim
# ---------------------------------------------------------------------------


class TestLegacyAIRegistry:
    def test_deprecation_warning(self):
        legacy = _LegacyAIRegistry()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            legacy.list_models  # noqa: B018
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    def test_provider_registry_is_registry_instance(self):
        assert isinstance(provider_registry, ProviderRegistry)
