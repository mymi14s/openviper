.. _ai_registry:

===========
AI Registry
===========

The ``openviper.ai`` package provides a unified, provider-agnostic abstraction
for large-language-model (LLM) inference, content moderation, and embeddings.
Multiple provider SDKs (OpenAI, Anthropic, Gemini, Ollama, Grok) are supported
out of the box and can be extended with custom providers via a plugin API.

.. contents:: On this page
   :local:
   :depth: 2

----

Registry Architecture
----------------------

The central component is :class:`~openviper.ai.registry.ProviderRegistry` —
a thread-safe dictionary that maps *model IDs* to *provider instances*.

.. code-block:: text

   ┌─────────────────────────────────────────────────────────┐
   │  ProviderRegistry                                       │
   │  ┌─────────────────┬─────────────────────────────────┐ │
   │  │  "gpt-4o"       │  OpenAIProvider(...)            │ │
   │  │  "gpt-4o-mini"  │  OpenAIProvider(...)            │ │
   │  │  "claude-3.5"   │  AnthropicProvider(...)         │ │
   │  │  "gemini-2.0"   │  GeminiProvider(...)            │ │
   │  │  "my-model-1"   │  CustomProvider(...)            │ │
   │  └─────────────────┴─────────────────────────────────┘ │
   └─────────────────────────────────────────────────────────┘
               │
               │  provider_registry.get_by_model("gpt-4o")
               ▼
        OpenAIProvider.generate(prompt)

The global registry singleton is:

.. code-block:: python

   from openviper.ai.registry import provider_registry

----

Built-in Providers
-------------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Provider key
     - Class
     - Models
   * - ``openai``
     - ``OpenAIProvider``
     - GPT-4o, GPT-4o Mini, GPT-3.5-Turbo, …
   * - ``anthropic``
     - ``AnthropicProvider``
     - Claude 3.5 Sonnet, Claude 3 Opus, …
   * - ``gemini``
     - ``GeminiProvider``
     - Gemini 2.0 Flash, Gemini 1.5 Pro, …
   * - ``ollama``
     - ``OllamaProvider``
     - Any locally hosted Ollama model
   * - ``grok``
     - ``GrokProvider``
     - Grok-2, Grok-2 Mini, …

----

Configuration via Settings
---------------------------

Enable the registry and configure providers in ``settings.py``:

.. code-block:: python

   import os

   ENABLE_AI_PROVIDERS = True

   AI_PROVIDERS = {
       "openai": {
           "provider": "openai",
           "api_key":  os.environ["OPENAI_API_KEY"],
           "models": {
               "gpt-4o":      "gpt-4o",
               "gpt-4o-mini": "gpt-4o-mini",
           },
       },
       "anthropic": {
           "provider": "anthropic",
           "api_key":  os.environ["ANTHROPIC_API_KEY"],
           "models": {
               "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
           },
       },
       "ollama": {
           "provider": "ollama",
           "base_url": "http://localhost:11434",
           "models": {
               "llama3": "llama3",
           },
       },
   }

OpenViper initialises and registers all configured providers at application
startup.

----

Making Inference Calls
-----------------------

Text Generation
~~~~~~~~~~~~~~~

.. code-block:: python

   from openviper.ai.registry import provider_registry

   provider = provider_registry.get_by_model("gpt-4o")
   response = await provider.generate(
       "Summarise the following article in 3 bullet points: ...",
       max_tokens = 200,
       temperature = 0.7,
   )
   print(response)   # plain string

Streaming
~~~~~~~~~~

.. code-block:: python

   provider = provider_registry.get_by_model("claude-3.5-sonnet")

   async for chunk in provider.stream("Write a haiku about async Python"):
       print(chunk, end="", flush=True)

Content Moderation
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   provider = provider_registry.get_by_model("gpt-4o")
   result   = await provider.moderate("User-generated content goes here.")

   print(result["classification"])   # "safe" | "spam" | "abusive" | "hate" | "sexual"
   print(result["confidence"])       # 0.0 – 1.0
   print(result["is_safe"])          # bool

Embeddings
~~~~~~~~~~

.. code-block:: python

   provider  = provider_registry.get_by_model("gpt-4o")
   embedding = await provider.embed("text to embed")
   # Returns list[float]; not all providers support embeddings

----

Listing Available Models
-------------------------

.. code-block:: python

   from openviper.ai.registry import provider_registry

   # All model IDs registered in the registry
   print(provider_registry.list_models())
   # ["gpt-4o", "gpt-4o-mini", "claude-3.5-sonnet", ...]

   # All provider names
   print(provider_registry.list_provider_names())
   # ["openai", "anthropic", "gemini"]

----

ModelRouter — Runtime Model Switching
---------------------------------------

:class:`~openviper.ai.router.ModelRouter` is a thread-safe wrapper around
``ProviderRegistry`` that lets you change the active AI model at runtime
without re-importing or reinitialising providers.  This is ideal for
applications that need to route requests to different models based on user
preferences, load, or feature flags.

.. code-block:: python

   from openviper.ai.router import model_router

   # Switch the active model at any time (thread-safe)
   model_router.set_model("gemini-2.0-flash")
   response = await model_router.generate("Summarise this article…")

   # Check which model is active
   print(model_router.get_model())   # "gemini-2.0-flash"

   # Use a different model for a single call
   result = await model_router.generate("Translate to French", model="claude-3.5-sonnet")

   # Streaming is supported the same way
   async for chunk in model_router.stream("Write a poem about the sea"):
       print(chunk, end="", flush=True)

The global singleton ``model_router`` is pre-wired to the application's
``provider_registry``.  For isolated contexts create a dedicated instance:

.. code-block:: python

   from openviper.ai.router import ModelRouter
   from openviper.ai.registry import provider_registry

   router = ModelRouter(registry=provider_registry, default_model="gpt-4o")

``ModelRouter`` exposes the same inference methods as individual providers:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Description
   * - ``.set_model(model_id)``
     - Switch the active model (thread-safe)
   * - ``.get_model()``
     - Return the currently active model ID
   * - ``.list_models()``
     - Return all model IDs from the registry
   * - ``await .generate(prompt, **kwargs)``
     - Generate a text response; uses active model unless ``model=`` is passed
   * - ``await .stream(prompt, **kwargs)``
     - Stream tokens; yields ``str`` chunks
   * - ``await .moderate(content, **kwargs)``
     - Moderate content; returns ``{classification, confidence, is_safe}``
   * - ``await .embed(text, **kwargs)``
     - Return an embedding vector

**Example — per-request model selection** (from
``examples/ai_moderation_platform``):

.. code-block:: python

   # moderation/ai_service.py
   from openviper.ai.router import ModelRouter

   _router = ModelRouter()

   class AIContentModerator:
       """Selects the AI model per request."""

       def __init__(self, model: str = "gpt-4o"):
           _router.set_model(model)

       async def moderate(self, content: str) -> dict:
           result = await _router.moderate(content)
           return {
               "is_safe":        result.get("is_safe", True),
               "classification": result.get("classification", "safe"),
               "confidence":     result.get("confidence", 1.0),
           }

----

Provider Abstraction Interface
--------------------------------

All providers implement :class:`~openviper.ai.base.AIProvider`:

.. code-block:: python

   import abc
   from typing import Any, AsyncIterator


   class AIProvider(abc.ABC):
       name: str               # provider identifier, e.g. "openai"
       default_model: str | None

       def __init__(self, config: dict[str, Any]) -> None: ...

       @abc.abstractmethod
       async def generate(self, prompt: str, **kwargs: Any) -> str:
           """Return a complete text response."""

       async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
           """Yield response tokens as they arrive."""

       async def moderate(self, content: str, **kwargs: Any) -> dict[str, Any]:
           """Classify content; returns classification, confidence, is_safe."""

       async def embed(self, text: str, **kwargs: Any) -> list[float]:
           """Return an embedding vector."""

       def supported_models(self) -> list[str]:
           """Return model IDs this provider can serve."""

       # Hooks — override to add pre/post processing
       async def before_inference(self, prompt: str, kwargs: dict) -> tuple[str, dict]: ...
       async def after_inference(self, prompt: str, response: str) -> str: ...

----

Writing a Custom Provider
--------------------------

Create a subclass of :class:`~openviper.ai.base.AIProvider`:

.. code-block:: python

   # myapp/ai/my_provider.py
   from openviper.ai.base import AIProvider


   class MyCustomProvider(AIProvider):
       """Calls an internal ML service."""

       name = "mycorp"

       def __init__(self, config: dict) -> None:
           super().__init__(config)
           self.base_url = config.get("base_url", "http://ml-service:8080")

       async def generate(self, prompt: str, **kwargs) -> str:
           import httpx
           async with httpx.AsyncClient() as client:
               resp = await client.post(
                   f"{self.base_url}/generate",
                   json={"prompt": prompt, **kwargs},
               )
               resp.raise_for_status()
               return resp.json()["text"]

       def supported_models(self) -> list[str]:
           return ["my-model-v1", "my-model-v2"]

Then register it in ``settings.py`` or at application startup:

.. rubric:: Via settings (string path)

.. code-block:: python

   AI_PROVIDERS = {
       "mycorp": {
           "provider": "myapp.ai.my_provider.MyCustomProvider",
           "base_url":  "http://ml-service:8080",
           "models":    {"my-model-v1": "my-model-v1"},
       },
   }

.. rubric:: Via code

.. code-block:: python

   from openviper.ai.registry import provider_registry
   from myapp.ai.my_provider import MyCustomProvider

   provider = MyCustomProvider({"base_url": "http://ml-service:8080"})
   provider_registry.register_provider(provider)

----

Plugin Discovery via Entry-Points
-----------------------------------

Third-party packages can expose providers automatically.  Declare an
entry-point in ``pyproject.toml``:

.. code-block:: toml

   [project.entry-points."openviper.ai.providers"]
   mycorp = "mypackage.providers:MyCustomProvider"

Then trigger discovery at startup:

.. code-block:: python

   from openviper.ai.registry import provider_registry

   provider_registry.discover_entrypoints()  # group = "openviper.ai.providers"

----

Streaming in a View
--------------------

Use :class:`~openviper.http.response.StreamingResponse` to forward tokens to
the client in real time:

.. code-block:: python

   from openviper import StreamingResponse
   from openviper.ai.registry import provider_registry


   @app.post("/ai/stream")
   async def stream_ai(request):
       body     = await request.json()
       prompt   = body.get("prompt", "")
       provider = provider_registry.get_by_model("gpt-4o")

       async def token_generator():
           async for chunk in provider.stream(prompt):
               yield chunk.encode()

       return StreamingResponse(token_generator(), media_type="text/plain")

----

Error Handling
---------------

.. code-block:: python

   from openviper.ai.exceptions import ModelNotFoundError, AIException

   try:
       provider = provider_registry.get_by_model("unknown-model")
   except ModelNotFoundError as exc:
       print(f"No provider for: {exc}")

   try:
       response = await provider.generate(prompt)
   except AIException as exc:
       print(f"Provider error: {exc}")

.. seealso::

   :ref:`settings` — ``ENABLE_AI_PROVIDERS`` and ``AI_PROVIDERS`` configuration keys.
