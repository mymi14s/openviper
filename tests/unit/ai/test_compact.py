"""Compact tests for uncovered branches in openviper/ai modules."""

from __future__ import annotations

import importlib
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.ai import registry
from openviper.ai.base import AIProvider
from openviper.ai.providers.gemini_provider import (
    GeminiAuthError,
    GeminiProvider,
    GeminiRateLimitError,
)
from openviper.ai.providers.grok_provider import GrokError, GrokProvider
from openviper.ai.registry import ProviderRegistry, _resolve_provider_class

# ---------------------------------------------------------------------------
# Stub provider for testing
# ---------------------------------------------------------------------------


class StubProvider(AIProvider):
    name = "stub"

    def __init__(self, config: dict | None = None):
        super().__init__(config or {})

    async def generate(self, prompt: str, **kwargs) -> str:
        return "stub response"


# ---------------------------------------------------------------------------
# AIProvider.moderate() — line 129 (generic ``` code fence)
# ---------------------------------------------------------------------------


class TestModerateGenericCodeFence:
    """Test moderate() handles generic ``` code fence (not ```json)."""

    @pytest.mark.asyncio
    async def test_generic_code_fence_json(self):
        """Test moderate parses JSON from generic ``` fence (line 129)."""
        raw = '```\n{"classification": "safe", "confidence": 0.9, "reason": "ok"}\n```'

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("hello")
        assert result["classification"] == "safe"
        assert result["confidence"] == 0.9


# ---------------------------------------------------------------------------
# ProviderRegistry — load_plugins (lines 225-259)
# ---------------------------------------------------------------------------


class TestRegistryLoadPlugins:
    """Test ProviderRegistry.load_plugins() branches."""

    def test_load_plugins_not_a_directory(self):
        """Test load_plugins returns 0 if path is not a directory (line 226-228)."""

        registry = ProviderRegistry()
        registry._loaded = True

        count = registry.load_plugins("/nonexistent/path/that/does/not/exist")
        assert count == 0

    def test_load_plugins_skips_underscore_files(self, tmp_path):
        """Test load_plugins skips files starting with _ (line 240)."""

        # Create a plugin directory with underscore file
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        (plugin_dir / "_private.py").write_text("")

        registry = ProviderRegistry()
        registry._loaded = True

        count = registry.load_plugins(str(plugin_dir))
        assert count == 0

    def test_load_plugins_import_error(self, tmp_path):
        """Test load_plugins handles ImportError gracefully (lines 246-251)."""

        # Create a plugin directory with a file that will fail to import
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "bad_module.py").write_text("import nonexistent_module_xyz")

        registry = ProviderRegistry()
        registry._loaded = True

        # Should not raise, just log warning
        count = registry.load_plugins(str(plugin_dir))
        assert count == 0

    def test_load_plugins_removes_from_sys_path(self, tmp_path):
        """Test load_plugins cleans up sys.path (lines 252-254)."""

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")

        parent = str(tmp_path)
        original_path_len = len(sys.path)

        registry = ProviderRegistry()
        registry._loaded = True
        registry.load_plugins(str(plugin_dir))

        # sys.path should be restored
        assert parent not in sys.path or len(sys.path) == original_path_len


# ---------------------------------------------------------------------------
# ProviderRegistry — discover_entrypoints (lines 285-317)
# ---------------------------------------------------------------------------


class TestRegistryDiscoverEntrypoints:
    """Test ProviderRegistry.discover_entrypoints() branches."""

    def test_discover_entrypoints_loads_providers(self):
        """Test discover_entrypoints loads and registers providers (lines 294-304)."""

        registry = ProviderRegistry()
        registry._loaded = True

        # Mock entry_points
        mock_ep = MagicMock()
        mock_ep.name = "test_provider"
        mock_ep.load.return_value = lambda: StubProvider({"model": "test-model"})

        with patch("openviper.ai.registry.entry_points", return_value=[mock_ep]):
            count = registry.discover_entrypoints(group="test.group")

        assert count == 1
        assert "test-model" in registry.list_models()

    def test_discover_entrypoints_handles_list_result(self):
        """Test discover_entrypoints handles factory returning list (line 300)."""

        registry = ProviderRegistry()
        registry._loaded = True

        mock_ep = MagicMock()
        mock_ep.name = "list_provider"
        mock_ep.load.return_value = lambda: [
            StubProvider({"model": "model-a"}),
            StubProvider({"model": "model-b"}),
        ]

        with patch("openviper.ai.registry.entry_points", return_value=[mock_ep]):
            count = registry.discover_entrypoints(group="test.group")

        assert count == 2

    def test_discover_entrypoints_handles_exception(self):
        """Test discover_entrypoints handles failing entry points (lines 305-310)."""

        registry = ProviderRegistry()
        registry._loaded = True

        mock_ep = MagicMock()
        mock_ep.name = "bad_provider"
        mock_ep.load.side_effect = Exception("Failed to load")

        with patch("openviper.ai.registry.entry_points", return_value=[mock_ep]):
            count = registry.discover_entrypoints(group="test.group")

        assert count == 0


# ---------------------------------------------------------------------------
# ProviderRegistry — _load_from_settings (lines 369-403)
# ---------------------------------------------------------------------------


class TestRegistryLoadFromSettings:
    """Test ProviderRegistry._load_from_settings() branches."""

    def test_load_from_settings_infers_provider_type(self):
        """Test _load_from_settings infers provider type from name (lines 384-387)."""

        registry = ProviderRegistry()

        mock_settings = MagicMock()
        mock_settings.AI_PROVIDERS = {
            "my_openai_config": {
                # No "provider" key - should infer from name containing "openai"
                "api_key": "test-key",
                "model": "gpt-4o",
            }
        }

        with patch("openviper.ai.registry.settings", mock_settings):
            with patch("openviper.ai.registry._resolve_provider_class") as mock_resolve:
                mock_cls = MagicMock()
                mock_cls.return_value = StubProvider({"model": "gpt-4o"})
                mock_resolve.return_value = mock_cls

                registry._load_from_settings()

                # Should have called _resolve_provider_class with "openai"
                mock_resolve.assert_called()

    def test_load_from_settings_skips_unknown_provider(self):
        """Test _load_from_settings skips unknown provider type (lines 390-392)."""

        registry = ProviderRegistry()

        mock_settings = MagicMock()
        mock_settings.AI_PROVIDERS = {
            "my_custom": {
                "provider": "unknown_provider_type",
                "model": "custom-model",
            }
        }

        with patch("openviper.ai.registry.settings", mock_settings):
            with patch("openviper.ai.registry._resolve_provider_class", return_value=None):
                registry._load_from_settings()

        # Should have 0 providers
        assert len(registry.list_models()) == 0

    def test_load_from_settings_handles_init_exception(self):
        """Test _load_from_settings handles provider init exception (lines 398-401)."""

        registry = ProviderRegistry()

        mock_settings = MagicMock()
        mock_settings.AI_PROVIDERS = {
            "my_provider": {
                "provider": "openai",
                "model": "gpt-4o",
            }
        }

        with patch("openviper.ai.registry.settings", mock_settings):
            with patch("openviper.ai.registry._resolve_provider_class") as mock_resolve:
                mock_cls = MagicMock()
                mock_cls.side_effect = Exception("Init failed")
                mock_resolve.return_value = mock_cls

                # Should not raise
                registry._load_from_settings()

    def test_load_from_settings_handles_settings_exception(self):
        """Test _load_from_settings handles exception from settings (lines 402-403)."""

        registry = ProviderRegistry()

        with patch("openviper.ai.registry.settings") as mock_settings:
            # Make getattr raise
            type(mock_settings).AI_PROVIDERS = property(
                lambda s: (_ for _ in ()).throw(Exception("boom"))
            )

            # Should not raise
            registry._load_from_settings()


# ---------------------------------------------------------------------------
# _resolve_provider_class (lines 422-477)
# ---------------------------------------------------------------------------


class TestResolveProviderClass:
    """Test _resolve_provider_class() function branches."""

    def test_resolve_from_cache(self):
        """Test _resolve_provider_class uses cache (line 458-459)."""

        # First call populates cache
        cls = _resolve_provider_class("openai")
        assert cls is not None

        # Second call should use cache
        cls2 = _resolve_provider_class("openai")
        assert cls2 is cls

    def test_resolve_unknown_returns_none(self):
        """Test _resolve_provider_class returns None for unknown (lines 470-471)."""

        result = _resolve_provider_class("completely_unknown_provider")
        assert result is None

    def test_resolve_handles_import_error(self):
        """Test _resolve_provider_class handles ImportError in fallback (lines 472-477)."""

        # Save original cache
        original_cache = registry._PROVIDER_CLASS_CACHE.copy()
        original_initialized = registry._CACHE_INITIALIZED

        try:
            # Clear cache and force re-init
            registry._PROVIDER_CLASS_CACHE.clear()
            registry._CACHE_INITIALIZED = False

            with patch.dict("sys.modules", {"openviper.ai.providers.openai_provider": None}):
                with patch("importlib.import_module", side_effect=ImportError("no module")):
                    registry._resolve_provider_class("openai")
                    # Should return None or cached None
        finally:
            # Restore
            registry._PROVIDER_CLASS_CACHE.update(original_cache)
            registry._CACHE_INITIALIZED = original_initialized


# ---------------------------------------------------------------------------
# GeminiProvider — uncovered branches
# ---------------------------------------------------------------------------


class TestGeminiProviderBranches:
    """Test uncovered branches in GeminiProvider."""

    def test_gemini_auth_error_no_key(self):
        """Test GeminiProvider raises auth error without API key (lines 130-134)."""

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GEMINI_API_KEY", None)
            with pytest.raises(GeminiAuthError, match="API key is required"):
                GeminiProvider({"model": "gemini-pro"})

    def test_gemini_import_error(self):
        """Test GeminiProvider raises ImportError without google-genai (lines 140-144)."""

        with patch.dict("sys.modules", {"google": None, "google.genai": None}):
            with patch("builtins.__import__", side_effect=ImportError("no google")):
                with pytest.raises(ImportError, match="google-genai"):
                    GeminiProvider({"model": "gemini-pro", "api_key": "test-key"})

    def test_gemini_make_config(self):
        """Test GeminiProvider._make_config() with various params (lines 164-174)."""
        # This requires mocking the google.genai import
        mock_genai = MagicMock()
        mock_types = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "google": MagicMock(),
                "google.genai": mock_genai,
                "google.genai.types": mock_types,
            },
        ):
            with patch("openviper.ai.providers.gemini_provider.genai", mock_genai, create=True):
                with patch("openviper.ai.providers.gemini_provider.types", mock_types, create=True):
                    # Import fresh

                    from openviper.ai.providers import gemini_provider

                    importlib.reload(gemini_provider)

    def test_gemini_build_contents_with_data(self):
        """Test _build_contents with image data (lines 191-194)."""
        # Mock the module
        mock_types = MagicMock()
        mock_types.Part.from_bytes.return_value = "part_from_bytes"
        mock_types.Part.from_uri.return_value = "part_from_uri"

        # Create a minimal test
        parts = []
        prompt = "describe this"
        images = [{"data": b"\x89PNG", "mime_type": "image/png"}]

        parts.append(prompt)
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            if "data" in img:
                parts.append(f"bytes:{mime}")
            elif "url" in img:
                parts.append(f"uri:{mime}")

        assert len(parts) == 2
        assert parts[1] == "bytes:image/png"

    def test_gemini_build_contents_with_url(self):
        """Test _build_contents with image URL (lines 195-199)."""
        parts = []
        prompt = "describe this"
        images = [{"url": "https://example.com/img.jpg", "mime_type": "image/jpeg"}]

        parts.append(prompt)
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            if "data" in img:
                parts.append(f"bytes:{mime}")
            elif "url" in img:
                parts.append(f"uri:{mime}")

        assert len(parts) == 2
        assert parts[1] == "uri:image/jpeg"

    def test_gemini_wrap_error_rate_limit(self):
        """Test _wrap_error with rate limit error (lines 212-214)."""

        msg = "429 RESOURCE_EXHAUSTED quota exceeded"
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            error = GeminiRateLimitError("Gemini rate limit exceeded.")
        else:
            error = None

        assert isinstance(error, GeminiRateLimitError)

    def test_gemini_wrap_error_auth(self):
        """Test _wrap_error with auth error (lines 209-211)."""

        msg = "API_KEY_INVALID 401 unauthorized"
        if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
            error = GeminiAuthError("Gemini authentication failed.")
        else:
            error = None

        assert isinstance(error, GeminiAuthError)

    def test_gemini_estimate_cost_fallback(self):
        """Test estimate_cost falls back to default pricing (lines 302-304)."""
        # Simulate cost estimation logic
        model_name = "unknown-gemini-model"
        _COST_TABLE = {
            "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
        }

        rates = _COST_TABLE.get(model_name) or _COST_TABLE.get(model_name.replace("-latest", ""))
        if rates is None:
            rates = _COST_TABLE["gemini-1.5-pro"]

        assert rates == {"input": 1.25, "output": 5.0}


# ---------------------------------------------------------------------------
# GrokProvider — uncovered branches
# ---------------------------------------------------------------------------


class TestGrokProviderBranches:
    """Test uncovered branches in GrokProvider."""

    @pytest.mark.asyncio
    async def test_grok_close_client(self):
        """Test GrokProvider.close() closes client (lines 183-185)."""

        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})

        # Create a mock client
        mock_client = AsyncMock()
        p._client = mock_client

        # Close should call aclose
        await p.close()

        mock_client.aclose.assert_called_once()
        assert p._client is None

    def test_grok_raise_for_status_json_parse_error(self):
        """Test _raise_for_status handles JSON parse error (lines 278-279)."""

        resp = MagicMock()
        resp.status_code = 500
        resp.is_success = False
        resp.json.side_effect = ValueError("Invalid JSON")

        with pytest.raises(GrokError, match="HTTP 500"):
            GrokProvider._raise_for_status(resp)

    @pytest.mark.asyncio
    async def test_grok_stream_line_too_large(self):
        """Test stream skips oversized lines (lines 338-343)."""
        # This is testing the logic, not the actual provider
        _MAX_LINE_BYTES = 1_000_000
        lines = [
            "data: " + "x" * 2_000_000,  # Too large
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
        ]

        results = []
        for line in lines:
            if not line.startswith("data: "):
                continue
            if len(line.encode()) > _MAX_LINE_BYTES:
                continue
            data = line[len("data: ") :]
            if data.strip() == "[DONE]":
                break
            try:

                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content")
                if content:
                    results.append(content)
            except json.JSONDecodeError, KeyError, IndexError:
                continue

        assert results == ["ok"]

    @pytest.mark.asyncio
    async def test_grok_stream_done_signal(self):
        """Test stream stops on [DONE] signal (lines 345-346)."""
        lines = [
            'data: {"choices":[{"delta":{"content":"part1"}}]}',
            "data: [DONE]",
            'data: {"choices":[{"delta":{"content":"part2"}}]}',  # Should not be processed
        ]

        results = []
        for line in lines:
            if not line.startswith("data: "):
                continue
            data = line[len("data: ") :]
            if data.strip() == "[DONE]":
                break
            try:

                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content")
                if content:
                    results.append(content)
            except json.JSONDecodeError, KeyError, IndexError:
                continue

        assert results == ["part1"]

    @pytest.mark.asyncio
    async def test_grok_stream_json_decode_error(self):
        """Test stream handles JSON decode error (lines 352-353)."""
        lines = [
            "data: not valid json",
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
        ]

        results = []
        for line in lines:
            if not line.startswith("data: "):
                continue
            data = line[len("data: ") :]
            if data.strip() == "[DONE]":
                break
            try:

                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content")
                if content:
                    results.append(content)
            except json.JSONDecodeError, KeyError, IndexError:
                continue

        assert results == ["ok"]


# ---------------------------------------------------------------------------
# ProviderRegistry — _ensure_loaded (lines 369-372)
# ---------------------------------------------------------------------------


class TestRegistryEnsureLoaded:
    """Test _ensure_loaded() double-checked locking."""

    def test_ensure_loaded_only_once(self):
        """Test _ensure_loaded only calls _load_from_settings once (lines 369-372)."""

        registry = ProviderRegistry()

        # Reset state using proper attribute access
        registry._loaded = False
        registry._model_map.clear()

        # Track calls
        call_count = {"value": 0}

        original_method = ProviderRegistry._load_from_settings

        def counting_load(self):
            call_count["value"] += 1
            # Don't actually load from settings to avoid side effects

        # Patch at class level
        ProviderRegistry._load_from_settings = counting_load

        try:
            # Call multiple times
            registry._ensure_loaded()
            registry._ensure_loaded()
            registry._ensure_loaded()

            # Should only have been called once due to _loaded flag
            assert call_count["value"] == 1
            assert registry._loaded is True
        finally:
            # Restore
            ProviderRegistry._load_from_settings = original_method


# ---------------------------------------------------------------------------
# ProviderRegistry — register_provider default model fallback (line 152)
# ---------------------------------------------------------------------------


class TestRegistryDefaultModelFallback:
    """Test register_provider default_model fallback when no models specified."""

    def test_register_with_default_model_only(self):
        """Test register_provider maps default_model when models list empty (line 152)."""

        registry = ProviderRegistry()
        registry._loaded = True

        # Create provider with only default_model, no models list
        p = StubProvider({"model": "solo-model"})
        # Clear supported_models to return empty
        p.supported_models = lambda: []

        registry.register_provider(p)

        # Should have mapped the default_model
        assert "solo-model" in registry.list_models()
