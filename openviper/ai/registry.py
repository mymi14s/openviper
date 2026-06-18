"""AI model registry - register and retrieve named providers."""

from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import sys
import threading
import warnings
from importlib.metadata import entry_points

from openviper.ai.base import AIProvider
from openviper.ai.providers import PROVIDER_TYPE_MAP
from openviper.conf import settings
from openviper.exceptions import ModelCollisionError, ModelNotFoundError

logger = logging.getLogger("openviper.ai")


@dataclasses.dataclass(slots=True, frozen=True)
class ProviderConfig:
    """Immutable configuration record for a single AI provider entry."""

    provider_type: str
    api_key: str = ""
    model: str = ""
    models: tuple[str, ...] = ()
    base_url: str = ""
    extra: dict[str, object] = dataclasses.field(default_factory=dict)


class ProviderRegistry:
    """Thread-safe registry mapping model IDs to provider instances."""

    __slots__ = ("_model_map", "_lock", "_loaded")

    ENTRYPOINT_GROUP = "openviper.ai.providers"

    def __init__(self) -> None:
        self._model_map: dict[str, AIProvider] = {}
        # RLock (reentrant) so that ensure_loaded → load_from_settings →
        # register_provider can re-acquire the lock on the same thread without
        # deadlocking.
        self._lock = threading.RLock()
        self._loaded = False

    def register_provider(self, provider: AIProvider, *, allow_override: bool = True) -> None:
        """Register all models exposed by *provider*.

        Raises ModelCollisionError when *allow_override* is False and a model ID is already claimed.
        """
        models = provider.supported_models()
        with self._lock:
            for model_id in models:
                existing = self._model_map.get(model_id)
                if existing is not None and existing is not provider:
                    if not allow_override:
                        raise ModelCollisionError(
                            model_id,
                            existing.provider_name(),
                            provider.provider_name(),
                        )
                    logger.warning(
                        "ProviderRegistry: model '%s' was claimed by '%s', now overridden by '%s'.",
                        model_id,
                        existing.provider_name(),
                        provider.provider_name(),
                    )
                self._model_map[model_id] = provider
            if not models and provider.default_model:
                self._model_map[provider.default_model] = provider
        logger.debug(
            "ProviderRegistry: registered %s with models %s",
            provider.provider_name(),
            models,
        )

    def register_from_module(self, module_path: str, *, allow_override: bool = True) -> int:
        """Import *module_path* and register providers from ``get_providers()`` or ``PROVIDERS``.

        Returns the number of provider instances registered.
        """
        mod = importlib.import_module(module_path)
        providers: list[AIProvider] = []

        get_providers_fn = getattr(mod, "get_providers", None)
        if callable(get_providers_fn):
            result = get_providers_fn()
            if isinstance(result, list):
                providers = result
        elif hasattr(mod, "PROVIDERS"):
            raw = mod.PROVIDERS
            if isinstance(raw, list):
                providers = raw

        count = 0
        for p in providers:
            if isinstance(p, AIProvider):
                self.register_provider(p, allow_override=allow_override)
                count += 1

        return count

    def load_plugins(self, plugin_dir: str, *, allow_override: bool = True) -> int:
        """Walk *plugin_dir* and register providers found in each ``.py`` file.

        Returns the total number of provider instances registered.
        Raises ValueError if *plugin_dir* contains path traversal sequences.
        """
        if ".." in plugin_dir.split(os.sep):
            raise ValueError(
                f"ProviderRegistry.load_plugins: path traversal in plugin_dir: {plugin_dir!r}"
            )

        plugin_dir = os.path.realpath(plugin_dir)

        if not os.path.isdir(plugin_dir):
            logger.warning("ProviderRegistry.load_plugins: %r is not a directory.", plugin_dir)
            return 0

        total = 0
        parent = os.path.dirname(plugin_dir)
        inserted = False
        with self._lock:
            if parent not in sys.path:
                sys.path.insert(0, parent)
                inserted = True

            try:
                plugin_pkg = os.path.basename(plugin_dir)
                for fname in sorted(os.listdir(plugin_dir)):
                    if not fname.endswith(".py") or fname.startswith("_"):
                        continue
                    stem = fname[:-3]
                    module_path = f"{plugin_pkg}.{stem}"
                    try:
                        total += self.register_from_module(
                            module_path, allow_override=allow_override
                        )
                    except ImportError as exc:
                        logger.warning(
                            "ProviderRegistry.load_plugins: could not import %r - %s",
                            module_path,
                            exc,
                        )
            finally:
                if inserted and parent in sys.path:
                    sys.path.remove(parent)

        return total

    def discover_entrypoints(
        self,
        group: str = ENTRYPOINT_GROUP,
        *,
        allow_override: bool = True,
    ) -> int:
        """Register providers declared via package entry-points in *group*.

        Returns the total number of provider instances registered.
        """
        eps = entry_points(group=group)
        total = 0
        for ep in eps:
            try:
                factory = ep.load()
                result = factory()
                instances = result if isinstance(result, list) else [result]
                for p in instances:
                    if isinstance(p, AIProvider):
                        self.register_provider(p, allow_override=allow_override)
                        total += 1
            except Exception as exc:
                logger.warning(
                    "ProviderRegistry.discover_entrypoints: entry-point %r failed - %s",
                    ep.name,
                    exc,
                )

        return total

    def get_by_model(self, model_id: str) -> AIProvider:
        """Return the provider registered for *model_id*.

        Raises ModelNotFoundError if no provider is registered for *model_id*.
        """
        self.ensure_loaded()
        # Lock-free read after initialization for better performance
        provider = self._model_map.get(model_id)
        if provider is None:
            raise ModelNotFoundError(model_id, self.list_models())
        return provider

    def list_models(self) -> list[str]:
        """Return all registered model IDs (sorted)."""
        self.ensure_loaded()
        # Lock-free read after initialization for better performance
        return sorted(self._model_map)

    def list_provider_names(self) -> list[str]:
        """Return the unique provider names that have been registered."""
        self.ensure_loaded()
        # Lock-free read after initialization for better performance
        return sorted({p.provider_name() for p in self._model_map.values()})

    def reset(self) -> None:
        """Clear all registrations and force a reload on next access (for tests)."""
        with self._lock:
            self._model_map.clear()
            self._loaded = False

    def ensure_loaded(self) -> None:
        """Load from settings exactly once (double-checked locking)."""
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self.load_from_settings()
                self._loaded = True

    def load_from_settings(self) -> None:
        """Instantiate providers from ``settings.AI_PROVIDERS`` and register them."""
        if not getattr(settings, "ENABLE_AI_PROVIDERS", False):
            return
        try:
            providers_cfg: dict[str, object] = getattr(settings, "AI_PROVIDERS", {}) or {}

            _known_providers = frozenset({"openai", "anthropic", "ollama", "gemini", "grok"})

            for name, spec in providers_cfg.items():
                provider_type = spec.get("provider")
                if not provider_type:
                    for known in _known_providers:
                        if known in name.lower():
                            provider_type = known
                            break

                cls = resolve_provider_class(provider_type or "")
                if cls is None:
                    logger.debug("ProviderRegistry: unknown provider type %r, skipping.", name)
                    continue

                cfg = {k: v for k, v in spec.items() if k != "provider"}
                try:
                    instance = cls(cfg)
                    self.register_provider(instance)
                except Exception as exc:
                    logger.warning(
                        "ProviderRegistry: could not initialise provider %r: %s", name, exc
                    )
        except Exception as exc:
            logger.error("ProviderRegistry: failed to load from settings: %s", exc)


PROVIDER_CLASS_CACHE: dict[str, type[AIProvider] | None] = {}

for type_key, dotted_path in PROVIDER_TYPE_MAP.items():
    try:
        module_path, cls_name = dotted_path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        PROVIDER_CLASS_CACHE[type_key] = getattr(mod, cls_name)
    except ImportError:
        PROVIDER_CLASS_CACHE[type_key] = None


def resolve_provider_class(provider_type: str) -> type[AIProvider] | None:
    """Return the provider class for *provider_type*, or ``None`` if unknown."""
    if provider_type in PROVIDER_CLASS_CACHE:
        return PROVIDER_CLASS_CACHE[provider_type]

    path = PROVIDER_TYPE_MAP.get(provider_type)
    if not path:
        return None
    try:
        module_path, cls_name = path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except (ImportError, AttributeError):
        return None


provider_registry = ProviderRegistry()


class LegacyAIRegistry:
    """Deprecated ai_registry shim that delegates to provider_registry."""

    def __getattr__(self, name: str) -> object:
        warnings.warn(
            "ai_registry is deprecated and will be removed in a future release. "
            "Use provider_registry instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(provider_registry, name)


ai_registry = LegacyAIRegistry()
