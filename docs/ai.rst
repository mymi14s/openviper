.. _ai:

AI Integration
===============

The ``openviper.ai`` package provides a unified, async-native AI provider
registry that abstracts multiple inference backends (OpenAI, Anthropic,
Gemini, Ollama, Grok, and custom providers) behind a single interface.

Installation
------------

The AI providers are an **optional** dependency.  Install them with:

.. code-block:: bash

    pip install openviper[ai]

This pulls in the ``openai``, ``anthropic``, and ``google-genai`` SDKs.
Providers that only need ``httpx`` (Ollama, Grok) work without the extra.

If you are developing locally from a clone of the repository:

.. code-block:: bash

    pip install -e '.[ai]'

Overview
--------

The package is organized around three concepts:

1. **AIProvider** - the abstract base class every provider implements.
2. **ProviderRegistry** - a thread-safe, model-centric registry that maps
   model IDs to provider instances and is auto-populated from
   ``settings.AI_PROVIDERS``.
3. **ModelRouter** - a high-level runtime-swappable client that resolves
   the active provider from the registry on each call.

A stable extension API (``openviper.ai.extension``) is provided for
third-party provider authors.

Key Classes & Functions
-----------------------

``openviper.ai.base``
~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AIProvider(config)

   Abstract base class for all AI providers.

   :param config: Provider configuration dict.  Supports ``"model"`` (str or
      dict with ``"default"`` key) and ``"models"`` (dict or list) keys.

   .. py:attribute:: name

      Provider identifier string (e.g. ``"openai"``).  Default: ``"base"``.

   .. py:method:: generate(prompt, **kwargs) -> Awaitable[str]

      Generate a text response for *prompt*.  Must be implemented by
      every concrete provider.

   .. py:method:: stream(prompt, **kwargs) -> AsyncIterator[str]

      Stream response chunks.  Optional - default implementation calls
      :meth:`generate` and yields the full string as a single chunk.

   .. py:method:: moderate(content, **kwargs) -> dict[str, object]

      Classify content for moderation.  Returns a dict with keys
      ``classification`` (str), ``confidence`` (float 0-1), ``reason`` (str),
      ``is_safe`` (bool), and ``truncated`` (bool).

   .. py:method:: supported_models() -> list[str]

      Return the sorted list of model IDs this provider can serve.

   .. py:method:: provider_name() -> str

      Return the canonical name for this provider.

   .. py:method:: embed(text, **kwargs) -> Awaitable[list[float]]

      Return an embedding vector.  Raises ``NotImplementedError`` by default.

   .. py:method:: before_inference(prompt, kwargs) -> Awaitable[tuple[str, dict]]

      Hook called before each inference.  Override to transform input.

   .. py:method:: after_inference(prompt, response) -> Awaitable[str]

      Hook called after each inference.  Override to transform output.

   .. py:method:: complete(prompt, **kwargs) -> Awaitable[str]

      Alias for :meth:`generate`.

   .. py:method:: stream_complete(prompt, **kwargs) -> AsyncIterator[str]

      Alias for :meth:`stream`.

``openviper.ai.registry``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ProviderConfig

   Immutable (frozen dataclass) configuration record for a single AI provider
   entry.  Produced from ``settings.AI_PROVIDERS`` dict entries.

   .. py:attribute:: provider_type

      Provider type string (e.g. ``"openai"``).  Required.

   .. py:attribute:: api_key

      API key string.  Default: ``""``.

   .. py:attribute:: model

      Default model name.  Default: ``""``.

   .. py:attribute:: models

      Tuple of model name strings.  Default: ``()``.

   .. py:attribute:: base_url

      Custom base URL.  Default: ``""``.

   .. py:attribute:: extra

      Extra provider-specific options.  Default: empty dict.

.. py:class:: ProviderRegistry

   Thread-safe registry mapping model IDs to :class:`AIProvider` instances.
   Auto-populated from ``settings.AI_PROVIDERS`` on first access via
   double-checked locking.

   .. py:method:: register_provider(provider, *, allow_override=True)

      Register all models exposed by *provider*.  Calls
      ``provider.supported_models()`` and maps each model ID to the provider.
      Raises :class:`~openviper.exceptions.ModelCollisionError` when
      *allow_override* is ``False`` and a model ID is already claimed.

   .. py:method:: register_from_module(module_path, *, allow_override=True) -> int

      Import *module_path* and register providers from its ``get_providers()``
      function or ``PROVIDERS`` variable.  Returns the count of registered
      providers.

   .. py:method:: load_plugins(plugin_dir, *, allow_override=True) -> int

      Walk *plugin_dir* and register providers found in each ``.py`` file.
      Raises ``ValueError`` if *plugin_dir* contains path traversal sequences.
      Returns the total number of providers registered.

   .. py:method:: discover_entrypoints(group=ENTRYPOINT_GROUP, *, allow_override=True) -> int

      Register providers declared via package entry-points in *group*.
      Returns the total number of providers registered.

   .. py:method:: get_by_model(model_id) -> AIProvider

      Return the provider registered for *model_id*.  Raises
      :class:`~openviper.exceptions.ModelNotFoundError` if not found.

   .. py:method:: list_models() -> list[str]

      Return all registered model IDs (sorted).

   .. py:method:: list_provider_names() -> list[str]

      Return the unique provider names that have been registered (sorted).

   .. py:method:: reset()

      Clear all registrations and force a reload on next access.

   .. py:attribute:: ENTRYPOINT_GROUP

      Default entry-point group name: ``"openviper.ai.providers"``.

.. py:data:: openviper.ai.registry.provider_registry

   The global :class:`ProviderRegistry` singleton.

.. py:function:: openviper.ai.registry.resolve_provider_class(provider_type) -> type[AIProvider] | None

   Return the provider class for *provider_type*, or ``None`` if unknown.
   Checks the pre-populated ``PROVIDER_CLASS_CACHE`` first, then falls back
   to ``PROVIDER_TYPE_MAP`` with dynamic import.

.. py:class:: LegacyAIRegistry

   Deprecated shim that delegates all attribute access to
   :data:`provider_registry`.  Emits ``DeprecationWarning`` on every access.

.. py:data:: openviper.ai.registry.ai_registry

   The global :class:`LegacyAIRegistry` singleton.  Deprecated; use
   :data:`provider_registry` instead.

``openviper.ai.router``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ModelRouter(registry=None, default_model=None)

   Runtime-swappable AI inference client.  All method calls are delegated
   to the provider registered for the current model.

   .. py:method:: set_model(model) -> None

      Switch the active model (thread-safe).

   .. py:method:: get_model() -> str | None

      Return the currently active model ID, or ``None`` if unset.

   .. py:method:: generate(prompt, *, model=None, **kwargs) -> Awaitable[str]

      Generate text using the active model's provider.

   .. py:method:: stream(prompt, *, model=None, **kwargs) -> AsyncIterator[str]

      Stream response chunks from the active model's provider.

   .. py:method:: moderate(content, *, model=None, **kwargs) -> dict[str, object]

      Classify content for moderation via the active model's provider.

   .. py:method:: embed(text, *, model=None, **kwargs) -> Awaitable[list[float]]

      Return an embedding vector via the active model's provider.

   .. py:method:: list_models() -> list[str]

      Return all model IDs currently registered in the ProviderRegistry.

.. py:data:: openviper.ai.router.model_router

   The global :class:`ModelRouter` singleton.

``openviper.ai.extension``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Stable public API for third-party provider authors.  Import from this
module to avoid depending on internal symbols:

.. code-block:: python

    from openviper.ai.extension import (
        AIProvider,
        provider_registry,
        AIException,
        ModelCollisionError,
        EXTENSION_API_VERSION,
    )

.. py:data:: EXTENSION_API_VERSION

   Tuple ``(1, 0)`` indicating the extension API version.  Bumped when
   the stable extension surface changes.

``openviper.ai.devkit``
~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for provider authors:

.. py:class:: SimpleProvider(AIProvider)

   Abstract provider base with convenience defaults.  Accepts ``name`` as a
   constructor keyword argument for ad-hoc instances without subclassing.

   .. py:method:: generate(prompt, **kwargs) -> Awaitable[str]

      Override this method to produce a text completion.

.. py:class:: StreamingAdapter(source, executor=None)

   Wrap a synchronous token generator into an ``AsyncIterator[str]``.
   The generator is consumed in a thread-pool executor so the event loop
   stays responsive.

   :param source: A ``Generator[str]`` or ``Callable[[], Generator[str]]``.
   :param executor: Optional ``concurrent.futures.Executor``.

.. py:function:: normalize_response(text) -> str

   Strip leading/trailing whitespace and collapse internal blank lines.

.. py:function:: map_http_error(status_code, detail="", *, provider="unknown", model="") -> AIException

   Convert an HTTP status code to the appropriate AI exception subclass.
   Maps 401/403 to :class:`ProviderNotAvailableError` (auth), 429 to
   :class:`ProviderNotAvailableError` (rate limit), 404 with *model* to
   :class:`ModelUnavailableError`, 500+ to :class:`ProviderNotAvailableError`
   (server error), and all others to a generic :class:`AIException`.

``openviper.ai.exceptions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AIException

   Base exception for all AI subsystem errors.  Re-exported from
   ``openviper.exceptions``.

.. py:class:: ProviderNotConfiguredError(AIException)

   Raised when a provider type is listed in settings but has no usable
   configuration.

   .. py:attribute:: provider

      The provider name string.

.. py:class:: ProviderNotAvailableError(AIException)

   Raised when a provider cannot be initialised (e.g. missing SDK or bad
   API key).

   .. py:attribute:: provider

      The provider name string.

   .. py:attribute:: reason

      Optional reason string.

.. py:class:: ModelUnavailableError(AIException)

   Raised when a model is registered but the underlying provider cannot
   serve it.

   .. py:attribute:: model

      The model ID string.

   .. py:attribute:: provider

      The provider name string.

   .. py:attribute:: reason

      Optional reason string.

Also re-exported from ``openviper.exceptions``:

.. py:class:: ModelCollisionError

   Raised when two providers claim the same model ID.

.. py:class:: ModelNotFoundError

   Raised when a requested model ID is not found in the registry.

``openviper.ai.types``
~~~~~~~~~~~~~~~~~~~~~~

Shared structural type aliases:

.. py:data:: AIConfig

   Type alias for ``dict[str, object]``.  General provider configuration.

.. py:data:: AIOptions

   Type alias for ``dict[str, object]``.  Per-call inference options.

.. py:data:: ModerationResult

   Type alias for ``dict[str, object]``.  Moderation output structure.

``openviper.ai.security``
~~~~~~~~~~~~~~~~~~~~~~~~~~

SSRF prevention utilities used by providers that accept user-supplied URLs.

.. py:data:: PRIVATE_NETWORKS

   List of ``ipaddress.IPv4Network`` / ``IPv6Network`` blocks representing
   private and reserved address ranges (10.0.0.0/8, 172.16.0.0/12,
   192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10, 127.0.0.0/8, ::1/128,
   fc00::/7, fe80::/10).

.. py:data:: LOCALHOST_HOSTS

   Frozenset of localhost hostname strings: ``{"localhost", "127.0.0.1",
   "::1", "0.0.0.0"}``.

.. py:function:: is_private_address(host) -> bool

   Return ``True`` if *host* resolves to a private or reserved IP address.

.. py:function:: validate_base_url(url, *, allow_localhost=False, provider="Provider")

   Raise ``ValueError`` if *url* targets a private address or uses an
   insecure scheme.  When *allow_localhost* is ``True``, ``http`` scheme
   and localhost addresses are permitted (for local providers like Ollama).

.. py:function:: validate_image_url(url, *, provider="Provider")

   Raise ``ValueError`` if *url* is non-HTTPS or targets a private address.
   No localhost exception - image URLs must always use HTTPS.

``openviper.ai.provider_utils``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared utilities for AI provider implementations.

.. py:data:: CHARS_PER_TOKEN

   Float ``4.0`` - approximate characters per token ratio.

.. py:data:: MAX_LINE_BYTES

   Int ``1048576`` (1 MiB) - maximum line size for streaming response
   parsing.

.. py:function:: filter_kwargs(kwargs, allowed, *, provider="Provider") -> dict[str, object]

   Return only whitelisted keys from *kwargs*.  Logs a warning for unknown
   keys.

   :param kwargs: Full keyword argument dict.
   :param allowed: Frozenset of permitted key names.
   :param provider: Provider name for warning messages.

.. py:function:: clamp_temperature(value, *, max_temp=2.0) -> float | None

   Clamp a temperature value between 0.0 and *max_temp*.  Returns ``None``
   for non-numeric or ``None`` inputs.

.. py:function:: count_tokens(text) -> int

   Estimate token count from character length using a 4:1 ratio.

.. py:function:: estimate_cost(input_tokens, output_tokens, cost_table, model, *, fallback_model=None) -> dict[str, float]

   Compute per-call cost from token counts and a provider cost table.
   Returns ``{"input_cost", "output_cost", "total_cost"}`` in USD
   (per-million-token rates).  Falls back to *fallback_model*, then the
   first entry in *cost_table*.

Built-in Providers
------------------

``openviper.ai.providers``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The providers package uses lazy imports - provider classes are only loaded
when first accessed.

.. py:data:: PROVIDER_MAP

   Dict mapping class names to dotted module paths for lazy loading:
   ``AnthropicProvider``, ``GeminiProvider``, ``GrokProvider``,
   ``OllamaProvider``, ``OpenAIProvider``.

.. py:data:: PROVIDER_TYPE_MAP

   Dict mapping short type keys to dotted class paths:
   ``"openai"``, ``"anthropic"``, ``"ollama"``, ``"gemini"``, ``"grok"``.

``openviper.ai.providers.openai_provider``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:class:: OpenAIProvider(AIProvider)

   OpenAI GPT provider using the ``openai`` SDK.

   :param config: Dict with ``api_key`` (or ``OPENAI_API_KEY`` env var),
      ``model``, ``base_url``, and optional kwargs.

   .. py:attribute:: name

      ``"openai"``

   Supports ``generate``, ``stream``, and ``embed``.

``openviper.ai.providers.anthropic_provider``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:class:: AnthropicProvider(AIProvider)

   Anthropic Claude provider using the ``anthropic`` SDK.

   :param config: Dict with ``api_key`` (or ``ANTHROPIC_API_KEY`` env var),
      ``model``, and optional kwargs.

   .. py:attribute:: name

      ``"anthropic"``

   Supports ``generate`` and ``stream``.

``openviper.ai.providers.gemini_provider``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:class:: GeminiProvider(AIProvider)

   Google Gemini AI provider using the ``google-genai`` SDK.

   :param config: Dict with ``api_key`` (or ``GEMINI_API_KEY`` env var),
      ``model``, ``embed_model``, ``temperature``, ``max_output_tokens``,
      ``candidate_count``, ``top_p``, ``top_k``.

   .. py:attribute:: name

      ``"gemini"``

   Supports ``generate``, ``stream``, and ``embed``.  Image inputs are
   validated via :func:`~openviper.ai.security.validate_image_url`.

   Provider-specific exceptions:

   .. py:class:: GeminiError(Exception)

      Base exception for Gemini provider errors.

   .. py:class:: GeminiAuthError(GeminiError)

      Raised when the API key is missing or invalid.

   .. py:class:: GeminiRateLimitError(GeminiError)

      Raised when the Gemini API rate limit is exceeded.

``openviper.ai.providers.grok_provider``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:class:: GrokProvider(AIProvider)

   xAI Grok provider using the OpenAI-compatible REST API via ``httpx``.

   :param config: Dict with ``api_key`` (or ``XAI_API_KEY`` env var),
      ``model``, ``base_url`` (default: ``"https://api.x.ai/v1"``).

   .. py:attribute:: name

      ``"grok"``

   Supports ``generate`` and ``stream``.  ``embed`` raises
   ``NotImplementedError``.  Base URL and image URLs are validated via
   :mod:`~openviper.ai.security`.

   Provider-specific exceptions:

   .. py:class:: GrokError(Exception)

      Base exception for Grok provider errors.

   .. py:class:: GrokAuthError(GrokError)

      Raised when the API key is missing or invalid.

   .. py:class:: GrokRateLimitError(GrokError)

      Raised when the xAI rate limit is exceeded.

``openviper.ai.providers.ollama_provider``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:class:: OllamaProvider(AIProvider)

   Ollama local LLM provider using ``httpx``.

   :param config: Dict with ``base_url`` (default:
      ``"http://localhost:11434"``), ``model``, and optional kwargs.

   .. py:attribute:: name

      ``"ollama"``

   Supports ``generate``, ``stream``, and ``embed``.  Base URL validation
   allows localhost (``allow_localhost=True``) via
   :func:`~openviper.ai.security.validate_base_url`.

Example Usage
-------------

.. seealso::

   Working projects that use the AI integration:

   - `examples/custom_provider_demo/ <https://github.com/mymi14s/openviper/tree/master/examples/custom_provider_demo>`_ - writing a custom ``AIProvider``, ``ProviderRegistry``, streaming
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - ``ModelRouter`` for content moderation, Ollama + Gemini config
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ - multiple AI service classes with ``ModelRouter``
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - AI chat assistant with caching

Registering & Using a Provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.ai.extension import AIProvider, provider_registry

    class EchoProvider(AIProvider):
        name = "echo"

        async def generate(self, prompt: str, **kwargs: object) -> str:
            return f"[Echo] {prompt}"

    # Register
    provider_registry.register_provider(
        EchoProvider({"models": {"Echo Model": "echo-v1"}}),
    )

    # Use via model router
    from openviper.ai.router import model_router

    model_router.set_model("echo-v1")
    result = await model_router.generate("Hello, world!")
    print(result)   # "[Echo] Hello, world!"

Configuration via Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import dataclasses
    import os
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
         AI_PROVIDERS: dict[str, object] = dataclasses.field(
            default_factory=lambda: {
                  "ollama": {
                     "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                     "models": {
                        "Granite Code 3B": "granite-code:3b",
                        "Qwen3 4B": "qwen3:4b",
                     },
                  },
                  "gemini": {
                     "api_key": os.environ.get("GEMINI_API_KEY"),
                     "model": {
                        "GEMINI 2.5 FLASH": "gemini-2.5-flash",
                        "GEMINI 3 PRO PREVIEW": "gemini-3-pro-preview",
                        "GEMINI 3 FLASH PREVIEW": "gemini-3-flash-preview",
                        "GEMINI 3.1 PRO PREVIEW": "gemini-3.1-pro-preview",
                     },
                     "embed_model": "models/text-embedding-004",
                     "temperature": 1.0,
                     "max_output_tokens": 2048,
                     "candidate_count": 1,
                     "top_p": 0.95,
                     "top_k": 40,
                  },
            }
         )

Streaming Response
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import StreamingResponse
    from openviper.ai.router import model_router

    @router.post("/ai/stream")
    async def stream_ai(request) -> StreamingResponse:
        body = await request.json()
        prompt = body.get("prompt", "")

        async def generate():
            async for chunk in model_router.stream(prompt):
                yield chunk.encode()

        return StreamingResponse(generate(), media_type="text/plain")

Content Moderation
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.ai.router import model_router

    result = await model_router.moderate("User-generated content here")
    print(result["is_safe"])        # bool
    print(result["classification"]) # "safe" | "spam" | "abusive" | "hate" | "sexual"
    print(result["confidence"])     # 0.0 - 1.0
    print(result["reason"])        # str

Embeddings
~~~~~~~~~~

.. code-block:: python

    from openviper.ai.router import model_router

    vector = await model_router.embed("Text to embed", model="text-embedding-004")
    print(len(vector))  # dimension count depends on the model
