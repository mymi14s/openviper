.. OpenViper documentation master file, version 0.0.1

.. _index:

=====================================
OpenViper |version| Documentation
=====================================

**OpenViper** is a production-ready, high-performance, async-first Python web framework designed to be
both flexible and batteries-included. It gives you the freedom of a minimal, unopinionated core when
you want control, while also providing a rich, fully integrated stack when you want to move fast.

Out of the box it includes a powerful ORM with model lifecycle and events, built-in authentication and
authorization, an Admin UI, background task processing, a pluggable AI provider registry, and automatic
OpenAPI documentation.

Whether you're building lean APIs or full-scale platforms, OpenViper scales with you — without forcing
you into rigid architectural constraints.

.. rubric:: Quick Example

The ``examples/flexible/app.py`` or ``examples/todoapp/`` in the repo is the minimal way to get started:

.. code-block:: python

   # examples/standard/app.py
   from openviper import OpenViper, JSONResponse
   from openviper.http.request import Request

   app = OpenViper(title="Standard Example API", version="1.0.0")

   @app.get("/")
   async def index(request: Request) -> JSONResponse:
       return JSONResponse({"message": "Hello, OpenViper!"})

   @app.get("/users/{user_id}")
   async def get_user(request: Request, user_id: int) -> JSONResponse:
       # ... fetch from DB
       return JSONResponse({"id": user_id})

.. code-block:: bash

   # Run it
   openviper run app       # from examples/standard/
   # Open: http://localhost:8000
   # Swagger: http://localhost:8000/open-api/docs

For a full example with auth, admin, templates, and ORM see ``examples/todoapp/``.
For a production-grade multi-app example with AI moderation see ``examples/ai_moderation_platform/``.

.. rubric:: Key highlights

* **Async-first** — every request handler, ORM query, and lifecycle hook is ``async``/``await`` native.
* **ORM** — models with full async support and model lifecycle.
* **Protected ORM** — role-based access enforcement at the query level, not just at the view level.
* **AI-native** — a unified :ref:`ai_registry` abstracts OpenAI, Anthropic, Gemini, Ollama, Grok and custom providers behind a single async API.
* **Admin panel** — automatic CRUD interface, auto-discovery, and role-based visibility.
* **Background tasks** — task queue with retry policies, priorities.
* **Periodic scheduler** — cron and interval scheduling built into the framework.
* **OpenAPI** — live Swagger and ReDoc UIs generated automatically from your routes.

----

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: Tutorial

   tutorial_blog

.. toctree::
   :maxdepth: 2
   :caption: Framework Reference

   architecture
   http
   orm
   serializers
   authentication
   admin
   tasks
   scheduler
   ai_registry
   storage
   exceptions

.. toctree::
   :maxdepth: 2
   :caption: Configuration & Operations

   settings
   cli
   deployment

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api_reference

----

.. rubric:: Indices and tables

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
