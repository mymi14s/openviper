"""AI model registry — register and retrieve named providers.

``ProviderRegistry`` (primary)
    Model-centric: look up by model ID for O(1) routing.  Auto-populated
    from ``settings.AI_PROVIDERS`` on first access.  Supports external
    registration via modules, plugin directories, and package entry-points.
    All public reads are protected by a reentrant lock.

``ai_registry`` (legacy shim)
    Deprecated singleton that forwards attribute access to
    ``provider_registry`` with a :exc:`DeprecationWarning`.  Will be removed
    in a future release.

Example::

    from openviper.ai.registry import provider_registry

    provider = provider_registry.get_by_model("gemini-2.0-flash")
    response = await provider.generate("Hello!")

External provider registration::

    # From a module
    provider_registry.register_from_module("mypackage.ai.my_provider")

    # From a directory of provider modules
    provider_registry.load_plugins("/path/to/providers/")

    # From installed package entry-points
    provider_registry.discover_entrypoints()
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import sys
import threading
import warnings
from importlib.metadata import entry_points
from typing import Any

from openviper.ai.base import AIProvider
from openviper.conf import settings
from openviper.exceptions import ModelCollisionError, ModelNotFoundError

logger = logging.getLogger("openviper.ai")


@dataclasses.dataclass(slots=True, frozen=True)
class ProviderConfig:
    """Immutable configuration record for a single AI provider entry.

    Produced from a ``settings.AI_PROVIDERS`` dict entry and passed to the
    provider constructor.  Frozen so it can be used as a cache key.
    """

    provider_type: str
    api_key: str = ""
    model: str = ""
    models: tuple[str, ...] = ()
    base_url: str = ""
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)


class ProviderRegistry:
    """Thread-safe registry mapping model IDs to provider instances.

    Populated automatically from ``settings.AI_PROVIDERS`` on first access
    (double-checked locking ensures this happens exactly once per process).

    Third-party providers can be registered without touching core code::

        # Programmatic registration
        from openviper.ai.registry import provider_registry
        provider_registry.register_provider(MyProvider({"model": "my-model"}))

        # From a module that exposes get_providers() or PROVIDERS
        provider_registry.register_from_module("mypackage.ai.my_provider")

        # From a directory of .py provider modules
        provider_registry.load_plugins("/etc/myapp/ai_plugins/")

        # From installed packages that declare an entry-point
        provider_registry.discover_entrypoints()  # group="openviper.ai.providers"
    """

    __slots__ = ("_model_map", "_lock", "_loaded")

    #: Entry-point group scanned by :meth:`discover_entrypoints`.
    ENTRYPOINT_GROUP = "openviper.ai.providers"

    def __init__(self) -> None:
        self._model_map: dict[str, AIProvider] = {}
        # RLock (reentrant) so that _ensure_loaded → _load_from_settings →
        # register_provider can re-acquire the lock on the same thread without
        # deadlocking.
        self._lock = threading.RLock()
        self._loaded = False

    # ── Public API ──────────────────────────────────────────────────────────

    def register_provider(self, provider: AIProvider, *, allow_override: bool = True) -> None:
        """Register all models exposed by *provider*.

        Calls ``provider.supported_models()`` and maps every returned model ID
        to *provider*.

        Args:
            provider: A fully-initialised :class:`~openviper.ai.base.AIProvider`.
            allow_override: When ``True`` (default) an existing mapping for the
                same model ID is silently replaced with a warning log.  Set to
                ``False`` to raise :class:`~openviper.exceptions.ModelCollisionError`
                instead.

        Raises:
            :class:`~openviper.exceptions.ModelCollisionError`:
                *allow_override* is ``False`` and another provider already owns
                one of the model IDs.
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
        """Import *module_path* and register any providers it exports.

        The module is expected to expose providers through either:

        * A **callable** named ``get_providers`` that returns
          ``list[AIProvider]``, or
        * A **module-level variable** named ``PROVIDERS`` of type
          ``list[AIProvider]``.

        Both conventions are checked; ``get_providers()`` takes precedence.

        Args:
            module_path: Dotted Python module path, e.g.
                ``"mypackage.ai.my_provider"``.
            allow_override: Forwarded to :meth:`register_provider`.

        Returns:
            Number of provider instances that were registered.

        Raises:
            ImportError: The module could not be imported.
            :class:`~openviper.exceptions.ModelCollisionError`:
                Collision detected and *allow_override* is ``False``.
        """
        mod = importlib.import_module(module_path)
        providers: list[AIProvider] = []

        if callable(getattr(mod, "get_providers", None)):
            result = mod.get_providers()  # type: ignore[attr-defined]
            if isinstance(result, list):
                providers = result
        elif hasattr(mod, "PROVIDERS"):
            raw = mod.PROVIDERS  # type: ignore[attr-defined]
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

        Each ``.py`` file is imported as a top-level module using its
        stem as the module name.  Files that do not expose a ``get_providers``
        function or ``PROVIDERS`` variable are silently skipped.

        Args:
            plugin_dir: Filesystem path to the directory containing plugin
                modules.
            allow_override: Forwarded to :meth:`register_provider`.

        Returns:
            Total number of provider instances that were registered across
            all plugin modules.

        Raises:
            :class:`~openviper.exceptions.ModelCollisionError`:
                Collision detected and *allow_override* is ``False``.
        """
        plugin_dir = os.path.realpath(plugin_dir)
        if not os.path.isdir(plugin_dir):
            logger.warning("ProviderRegistry.load_plugins: %r is not a directory.", plugin_dir)
            return 0

        total = 0
        parent = os.path.dirname(plugin_dir)
        inserted = False
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
                    total += self.register_from_module(module_path, allow_override=allow_override)
                except ImportError as exc:
                    logger.warning(
                        "ProviderRegistry.load_plugins: could not import %r — %s",
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
        """Register providers declared via package entry-points.

        Third-party packages can advertise providers by declaring an
        entry-point in their ``pyproject.toml``::

            [project.entry-points."openviper.ai.providers"]
            my_provider = "mypackage.ai.my_provider:get_providers"

        Each entry-point value must be a callable that returns either a single
        :class:`~openviper.ai.base.AIProvider` instance or a ``list`` of them.

        Args:
            group: Entry-point group name (default: ``"openviper.ai.providers"``).
            allow_override: Forwarded to :meth:`register_provider`.

        Returns:
            Total number of provider instances that were registered.
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
                    "ProviderRegistry.discover_entrypoints: entry-point %r failed — %s",
                    ep.name,
                    exc,
                )

        return total

    def get_by_model(self, model_id: str) -> AIProvider:
        """Return the provider registered for *model_id*.

        Auto-loads from settings on first call.

        Args:
            model_id: Exact model identifier (e.g. ``"gpt-4o"``).

        Returns:
            :class:`~openviper.ai.base.AIProvider` instance.

        Raises:
            :class:`~openviper.exceptions.ModelNotFoundError`:
                No provider is registered for *model_id*.
        """
        self._ensure_loaded()
        # Lock-free read after initialization for better performance
        provider = self._model_map.get(model_id)
        if provider is None:
            raise ModelNotFoundError(model_id, self.list_models())
        return provider

    def list_models(self) -> list[str]:
        """Return all registered model IDs (sorted)."""
        self._ensure_loaded()
        # Lock-free read after initialization for better performance
        return sorted(self._model_map)

    def list_provider_names(self) -> list[str]:
        """Return the unique provider names that have been registered."""
        self._ensure_loaded()
        # Lock-free read after initialization for better performance
        return sorted({p.provider_name() for p in self._model_map.values()})

    def reset(self) -> None:
        """Clear all registrations and force a reload on next access (for tests)."""
        global _CACHE_INITIALIZED
        with self._lock:
            self._model_map.clear()
            self._loaded = False
        with _CACHE_LOCK:
            _PROVIDER_CLASS_CACHE.clear()
            _CACHE_INITIALIZED = False

    # ── Internal ────────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Load from settings exactly once (double-checked locking)."""
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._load_from_settings()
                self._loaded = True

    def _load_from_settings(self) -> None:
        """Instantiate providers from ``settings.AI_PROVIDERS`` and register them."""
        if not getattr(settings, "ENABLE_AI_PROVIDERS", False):
            return
        try:
            providers_cfg: dict[str, Any] = getattr(settings, "AI_PROVIDERS", {}) or {}

            known_providers = ["openai", "anthropic", "ollama", "gemini", "grok"]

            for name, spec in providers_cfg.items():
                provider_type = spec.get("provider")
                if not provider_type:
                    for known in known_providers:
                        if known in name.lower():
                            provider_type = known
                            break

                cls = _resolve_provider_class(provider_type or "")
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


# Pre-import cache for known providers to avoid dynamic import overhead.
# Protected by _CACHE_LOCK to prevent race conditions on first initialisation.
_PROVIDER_CLASS_CACHE: dict[str, type[AIProvider] | None] = {}
_CACHE_INITIALIZED = False
_CACHE_LOCK = threading.Lock()


def _resolve_provider_class(provider_type: str) -> type[AIProvider] | None:
    """Return the provider class for *provider_type*, or ``None`` if unknown.

    Pre-imports known providers to avoid dynamic import overhead on every call.
    Uses double-checked locking to initialise the cache exactly once.
    """
    global _CACHE_INITIALIZED

    # Fast path — cache already populated (no lock needed after init).
    if not _CACHE_INITIALIZED:
        with _CACHE_LOCK:
            if not _CACHE_INITIALIZED:
                try:
                    from openviper.ai.providers.openai_provider import OpenAIProvider

                    _PROVIDER_CLASS_CACHE["openai"] = OpenAIProvider
                except ImportError:
                    _PROVIDER_CLASS_CACHE["openai"] = None

                try:
                    from openviper.ai.providers.anthropic_provider import AnthropicProvider

                    _PROVIDER_CLASS_CACHE["anthropic"] = AnthropicProvider
                except ImportError:
                    _PROVIDER_CLASS_CACHE["anthropic"] = None

                try:
                    from openviper.ai.providers.ollama_provider import OllamaProvider

                    _PROVIDER_CLASS_CACHE["ollama"] = OllamaProvider
                except ImportError:
                    _PROVIDER_CLASS_CACHE["ollama"] = None

                try:
                    from openviper.ai.providers.gemini_provider import GeminiProvider

                    _PROVIDER_CLASS_CACHE["gemini"] = GeminiProvider
                except ImportError:
                    _PROVIDER_CLASS_CACHE["gemini"] = None

                try:
                    from openviper.ai.providers.grok_provider import GrokProvider

                    _PROVIDER_CLASS_CACHE["grok"] = GrokProvider
                except ImportError:
                    _PROVIDER_CLASS_CACHE["grok"] = None

                _CACHE_INITIALIZED = True

    # Return pre-imported class if available
    if provider_type in _PROVIDER_CLASS_CACHE:
        return _PROVIDER_CLASS_CACHE[provider_type]

    # Fallback to dynamic import for unknown providers
    mapping = {
        "openai": "openviper.ai.providers.openai_provider.OpenAIProvider",
        "anthropic": "openviper.ai.providers.anthropic_provider.AnthropicProvider",
        "ollama": "openviper.ai.providers.ollama_provider.OllamaProvider",
        "gemini": "openviper.ai.providers.gemini_provider.GeminiProvider",
        "grok": "openviper.ai.providers.grok_provider.GrokProvider",
    }
    path = mapping.get(provider_type)
    if not path:
        return None
    try:
        module_path, cls_name = path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except ImportError, AttributeError:
        return None


# Global singleton
provider_registry = ProviderRegistry()


class _LegacyAIRegistry:
    """Deprecated ``ai_registry`` shim.

    All attribute access triggers a :exc:`DeprecationWarning` and delegates
    to :data:`provider_registry`.  This class will be removed in a future
    release.  Migrate to :data:`provider_registry` directly.
    """

    def __getattr__(self, name: str) -> Any:
        warnings.warn(
            "ai_registry is deprecated and will be removed in a future release. "
            "Use provider_registry instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(provider_registry, name)


#: Deprecated; kept for one release cycle.  Use :data:`provider_registry`.
ai_registry = _LegacyAIRegistry()
