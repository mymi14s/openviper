.. _architecture:

====================
Core Architecture
====================

OpenViper is built on top of the **ASGI** standard (Asynchronous Server Gateway
Interface — `PEP 3333 <https://peps.python.org/pep-3333/>`_ extension).  Every
request is processed as an async coroutine from the moment it arrives at the
server to the moment the response bytes leave the socket.

.. contents:: On this page
   :local:
   :depth: 2

----

ASGI and Uvicorn
-----------------

The entry-point for every OpenViper project is an ``asgi.py`` module that exposes
an ASGI-compatible callable:

.. code-block:: python

   # myproject/asgi.py
   from openviper import OpenViper
   from myproject.settings import Settings
   from openviper.conf import configure

   configure(Settings())

   app = OpenViper(title="My API", version="1.0.0")

   # include routers ...

**Uvicorn** is the recommended ASGI server.  It is included as a direct
dependency and is invoked by ``python viperctl.py runserver``:

.. code-block:: bash

   uvicorn myproject.asgi:app --host 0.0.0.0 --port 8000 --workers 4

----

Application Lifecycle
----------------------

The :class:`~openviper.app.OpenViper` class implements the ASGI interface
(``scope`` / ``receive`` / ``send`` triple) and manages the full application
lifecycle.

Startup and shutdown hooks allow you to initialise expensive resources
(database connection pools, AI provider clients, caches) once per process:

.. code-block:: python

   @app.on_startup
   async def startup():
       await database.connect()

   @app.on_shutdown
   async def shutdown():
       await database.disconnect()

These are called by Uvicorn's lifespan protocol before/after request handling
begins.

----

Request Processing Pipeline
-----------------------------

.. code-block:: text

   Browser / Client
        │
        ▼  TCP / TLS
   ┌──────────────────────────────────────────────────────────┐
   │  Uvicorn  (ASGI server)                                  │
   └──────────────────────────────────────────────────────────┘
        │  scope / receive / send
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  OpenViper.__call__                                      │
   │  Builds Request, invokes middleware chain                │
   └──────────────────────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Middleware Stack (outermost → innermost)                │
   │  SecurityMiddleware                                      │
   │  CORSMiddleware                                          │
   │  AuthenticationMiddleware  ← populates request.user     │
   │  CSRFMiddleware                                          │
   │  RateLimitMiddleware                                     │
   │  AdminMiddleware                                         │
   │  … custom middleware …                                   │
   └──────────────────────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Router.resolve(method, path)                            │
   │  Matches URL pattern, extracts path params               │
   └──────────────────────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  View / Handler                                          │
   │  async def my_view(request, **path_params) → Response    │
   └──────────────────────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Response.__call__  → sends HTTP bytes via `send`        │
   └──────────────────────────────────────────────────────────┘

----

The OpenViper Application Object
----------------------------------

``OpenViper`` — defined in :mod:`openviper.app` — is simultaneously:

* An **ASGI callable** (``__call__``)
* A **route decorator registry** (``get``, ``post``, …)
* A **lifecycle hook registry** (``on_startup``, ``on_shutdown``)
* An **exception handler registry** (``exception_handler``)

.. code-block:: python

   from openviper import OpenViper

   app = OpenViper(
       title       = "My Service",
       version     = "1.0.0",
       debug       = True,
       openapi_url = "/open-api/openapi.json",
       docs_url    = "/open-api/docs",
       redoc_url   = "/open-api/redoc",
   )

   # Function-based route
   @app.get("/health")
   async def health(request):
       return {"status": "ok"}

   # Sub-router
   from myapp.routes import router as api_router
   app.include_router(api_router, prefix="/api/v1")

----

Routing
--------

Routing is handled by :class:`~openviper.routing.router.Router`.  Routes are
registered with HTTP method, path pattern, and handler.  Path parameters are
extracted via ``{param}`` syntax and passed as keyword arguments to the handler:

.. code-block:: python

   from openviper.routing.router import Router

   router = Router()

   @router.get("/posts/{slug}")
   async def get_post(request, slug: str):
       ...

   # Class-based views
   from openviper.http.views import View

   class PostView(View):
       async def get(self, request, slug: str):
           ...
       async def put(self, request, slug: str):
           ...

   PostView.register(router, "/posts/{slug}")

   # URL reverse
   router.url_for("get_post", slug="hello-world")
   # → "/posts/hello-world"

----

Middleware System
------------------

Middleware classes wrap the ASGI application in an onion pattern.  Each
middleware receives ``scope``, ``receive``, and ``send`` and is responsible
for calling the inner application (``await self.app(scope, receive, send)``).

Built-in middleware (applied in order):

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Class
     - Responsibility
   * - ``SecurityMiddleware``
     - Sets security headers (HSTS, X-Frame-Options, X-Content-Type-Options, …)
   * - ``CORSMiddleware``
     - Adds ``Access-Control-*`` headers; handles preflight OPTIONS
   * - ``AuthenticationMiddleware``
     - Reads JWT / session, sets ``request.user``
   * - ``CSRFMiddleware``
     - Validates CSRF token for state-changing requests
   * - ``RateLimitMiddleware``
     - Enforces per-IP (or per-user) rate limits
   * - ``AdminMiddleware``
     - Mounts the admin SPA static assets and API

Writing custom middleware:

.. code-block:: python

   from openviper.middleware.base import BaseMiddleware

   class TimingMiddleware(BaseMiddleware):
       async def __call__(self, scope, receive, send):
           import time
           start = time.perf_counter()
           await self.app(scope, receive, send)
           elapsed = time.perf_counter() - start
           print(f"{scope.get('method')} {scope.get('path')} — {elapsed:.3f}s")

   # Register in settings.py
   MIDDLEWARE = (
       "openviper.middleware.security.SecurityMiddleware",
       "openviper.middleware.cors.CORSMiddleware",
       "openviper.middleware.auth.AuthenticationMiddleware",
       "myapp.middleware.TimingMiddleware",     # ← custom
       ...
   )

----

Dependency Management
----------------------

Python dependencies are managed via ``pyproject.toml`` (setuptools) and
``requirements.txt``.  The framework supports optional groups:

.. code-block:: bash

   pip install "openviper[postgresql,tasks,ai]"

At runtime, optional providers are imported lazily so the core package does
not fail if optional dependencies are absent.

----

OpenAPI Integration
--------------------

OpenViper automatically generates an OpenAPI 3.x schema from registered
routes.  The schema is served at ``OPENAPI_SCHEMA_URL`` and rendered by:

* **Swagger UI** at ``OPENAPI_DOCS_URL`` (default ``/open-api/docs``)
* **ReDoc** at ``OPENAPI_REDOC_URL`` (default ``/open-api/redoc``)

To invalidate and regenerate the cached schema:

.. code-block:: python

   app.invalidate_openapi_schema()

.. seealso::

   :ref:`settings` for all ``OPENAPI_*`` configuration keys.

----

Subsystem Overview
-------------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Package
     - Responsibility
   * - ``openviper.app``
     - Top-level ASGI callable and route registry
   * - ``openviper.routing``
     - URL pattern matching and reverse lookup
   * - ``openviper.http``
     - Request, Response, and CBV base classes
   * - ``openviper.middleware``
     - Pluggable ASGI middleware chain
   * - ``openviper.db``
     - Async ORM — models, fields, migrations
   * - ``openviper.auth``
     - Users, roles, permissions, JWT, sessions
   * - ``openviper.serializers``
     - Pydantic-backed validation and serialization
   * - ``openviper.admin``
     - Auto-discovery admin panel with Vue SPA
   * - ``openviper.tasks``
     - Dramatiq background tasks and model events
   * - ``openviper.ai``
     - AI provider registry and abstraction layer
   * - ``openviper.conf``
     - Frozen settings dataclass
   * - ``openviper.core``
     - Management commands, context, app resolver
   * - ``openviper.openapi``
     - Schema generation and Swagger / ReDoc UIs
   * - ``openviper.staticfiles``
     - Static file middleware and collectstatic
