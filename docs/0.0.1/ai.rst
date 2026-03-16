.. _ai:

AI Integration
==============

The ``openviper.ai`` package provides a unified, async-native AI provider
registry that abstracts multiple inference backends (OpenAI, Anthropic,
Gemini, Ollama, Grok, and custom providers) behind a single interface.

Overview
--------

The package is organized around three concepts:

1. **AIProvider** — the abstract base class every provider implements.
2. **ProviderRegistry** — a thread-safe, model-centric registry that maps
   model IDs to provider instances and is auto-populated from
   ``settings.AI_PROVIDERS``.
3. **ModelRouter** — a high-level runtime-swappable client that resolves
   the active provider from the registry on each call.

A stable extension API (``openviper.ai.extension``) is provided for
third-party provider authors.

Key Classes & Functions
-----------------------

``openviper.ai.base``
~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AIProvider(config)

   Abstract base class for all AI providers.

   .. py:attribute:: name

      Provider identifier string (e.g. ``"openai"``).

   .. py:method:: generate(prompt, **kwargs) -> Awaitable[str]

      Generate a text response for *prompt*.  Must be implemented by
      every concrete provider.

   .. py:method:: stream(prompt, **kwargs) -> AsyncIterator[str]

      Stream response chunks.  Optional — default implementation calls
      :meth:`generate` and yields the full string as a single chunk.

``openviper.ai.registry``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ProviderRegistry

   Thread-safe registry mapping model IDs to :class:`AIProvider` instances.

   .. py:method:: register(provider, model_id, allow_override=False)

      Register *provider* under *model_id*.  Raises
      :class:`~openviper.exceptions.ModelCollisionError` if *model_id* is
      already taken and ``allow_override=False``.

   .. py:method:: get_by_model(model_id) -> AIProvider

      Return the provider for *model_id*.  Raises
      :class:`~openviper.exceptions.ModelNotFoundError` if not found.

   .. py:method:: list_models() -> list[str]

      Return all registered model IDs.

   .. py:method:: register_from_module(dotted_path)

      Import a module and call its ``get_providers()`` function to register
      providers from third-party packages.

   .. py:method:: load_plugins(directory)

      Scan a directory for provider modules and register them.

   .. py:method:: discover_entrypoints()

      Discover and register providers from installed package entry-points
      under the ``openviper.ai.providers`` group.

.. py:data:: openviper.ai.registry.provider_registry

   The global :class:`ProviderRegistry` singleton.

``openviper.ai.router``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ModelRouter(registry=None, default_model=None)

   Runtime-swappable AI inference client.  All method calls are delegated
   to the provider registered for the current model.

   .. py:method:: set_model(model_id) -> None

      Switch the active model (thread-safe).

   .. py:method:: get_model() -> str | None

      Return the currently active model ID.

   .. py:method:: generate(prompt, **kwargs) -> Awaitable[str]

      Generate text using the active model's provider.

   .. py:method:: stream(prompt, **kwargs) -> AsyncIterator[str]

      Stream response chunks from the active model's provider.

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
        ModelCollisionError,
        EXTENSION_API_VERSION,
    )

``openviper.ai.devkit``
~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for provider authors:

.. py:class:: SimpleProvider(AIProvider)

   Abstract base with sensible defaults.  Accepts ``name`` as a constructor
   keyword argument.

.. py:function:: normalize_response(text) -> str

   Strip leading/trailing whitespace and normalize line endings.

.. py:function:: map_http_error(status_code) -> AIException

   Convert an HTTP status code to the appropriate AI exception subclass.

Example Usage
-------------

.. seealso::

   Working projects that use the AI integration:

   - `examples/custom_provider_demo/ <https://github.com/mymi14s/openviper/tree/master/examples/custom_provider_demo>`_ — writing a custom ``AIProvider``, ``ProviderRegistry``, streaming
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — ``ModelRouter`` for content moderation, Ollama + Gemini config
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ — multiple AI service classes with ``ModelRouter``
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — AI chat assistant with caching

Registering & Using a Provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.ai.extension import AIProvider, provider_registry
    from typing import Any

    class EchoProvider(AIProvider):
        name = "echo"

        async def generate(self, prompt: str, **kwargs: Any) -> str:
            return f"[Echo] {prompt}"

    # Register
    provider_registry.register(
        EchoProvider({"models": {"Echo Model": "echo-v1"}}),
        model_id="echo-v1",
    )

    # Use via model router
    from openviper.ai.router import model_router

    model_router.set_model("echo-v1")
    result = await model_router.generate("Hello, world!")
    print(result)   # "[Echo] Hello, world!"

Configuration via Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import dataclasses, os
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
         AI_PROVIDERS: dict[str, Any] = dataclasses.field(
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
