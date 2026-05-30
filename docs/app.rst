.. _app:

The OpenViper Application
==========================

The ``openviper.app`` module contains the central :class:`~openviper.app.OpenViper`
class - the entry point for all request handling.  It ties together routing,
middleware, dependency injection, exception handling, and OpenAPI schema
generation into a single ASGI application.

.. rubric:: Quick Start

.. code-block:: python

   from openviper import OpenViper

   app = OpenViper(title="My API", version="1.0.0")

   @app.get("/")
   async def index(request):
       return {"message": "Hello, World!"}

The ``app`` instance is an ASGI callable, so it can be passed directly to an
ASGI server such as uvicorn:

.. code-block:: bash

   uvicorn myproject.app:app

OpenViper Class
---------------

.. py:class:: openviper.app.OpenViper(debug=None, middleware=None, title=None, version=None, description=None, openapi_url=None, docs_url=None, redoc_url=None)

   The central ASGI application class.  Acts as both an ASGI callable and a
   router decorator, so routes are registered directly on the app instance.

   :param debug: Enable debug mode (overrides ``settings.DEBUG`` when set).
   :param middleware: Extra middleware entries to prepend to the stack.
      Each entry is either a middleware class or a
      ``(cls, kwargs_dict)`` tuple.
   :param title: OpenAPI document title.  Falls back to
      ``settings.OPENAPI["title"]``.
   :param version: API version string.  Falls back to
      ``settings.OPENAPI["version"]``.
   :param description: OpenAPI description.  Falls back to
      ``settings.OPENAPI["description"]``.
   :param openapi_url: URL path for the OpenAPI JSON schema.
   :param docs_url: URL path for the Swagger UI.
   :param redoc_url: URL path for the ReDoc UI.

   .. py:method:: get(path, **kwargs)
   .. py:method:: post(path, **kwargs)
   .. py:method:: put(path, **kwargs)
   .. py:method:: patch(path, **kwargs)
   .. py:method:: delete(path, **kwargs)
   .. py:method:: options(path, **kwargs)

      Decorator shortcuts that delegate to the internal
      :class:`~openviper.routing.router.Router`.  Register a handler for the
      corresponding HTTP method on *path*.

   .. py:method:: route(path, methods, **kwargs)

      Register a handler for *path* matching the given *methods* list.

   .. py:method:: include_router(router, prefix="")

      Mount a sub-:class:`~openviper.routing.router.Router`.  When *prefix*
      is given, it is prepended to all routes in the sub-router.

   .. py:method:: on_startup(func)

      Register a startup lifecycle handler.  *func* may be a plain function
      or an ``async`` coroutine.  Called during the ASGI ``lifespan.startup``
      event.

   .. py:method:: on_shutdown(func)

      Register a shutdown lifecycle handler.  Called during the ASGI
      ``lifespan.shutdown`` event, in registration order.

   .. py:method:: exception_handler(exc_class)

      Decorator that registers a custom exception handler for *exc_class*.
      When an exception of that type (or a subclass) escapes a handler, the
      registered callback is invoked with ``(request, exc)`` and must return
      a :class:`~openviper.http.response.Response`.

   .. py:method:: get_openapi_schema() -> dict

      Return the generated OpenAPI schema dict.  The result is cached after
      the first call; use :meth:`invalidate_openapi_schema` to force
      regeneration.

   .. py:method:: invalidate_openapi_schema()

      Clear the cached OpenAPI schema so it is regenerated on the next
      request.

   .. py:method:: invalidate_middleware_cache()

      Clear the cached middleware stack.  Useful when routes or middleware
      are added dynamically after initial setup.

   .. py:method:: coerce_response(result) -> Response

      Convert a handler's return value into a proper
      :class:`~openviper.http.response.Response`.  Supports dicts, lists,
      strings, bytes, ``None``, Pydantic models, and objects with a
      ``model_dump()`` method.

   .. py:method:: call_handler(handler, request) -> Response

      Invoke *handler* with the appropriate parameters extracted from
      *request*.  Performs automatic response coercion via
      :meth:`coerce_response`.

   .. py:method:: resolve_middleware(raw_middleware) -> list

      Resolve a list of middleware entries (strings or classes) into their
      corresponding classes.  When a ``CORSMiddleware`` entry is found, its
      keyword arguments are wired from settings automatically.

   .. py:method:: cors_kwargs() -> dict

      Build the keyword arguments for
      :class:`~openviper.middleware.cors.CORSMiddleware` from the current
      settings.

   .. py:method:: run(host="127.0.0.1", port=8000, reload=True, log_level="info", workers=1)

      Start a uvicorn development server.  Prefer ``viperctl start-server``
      for production deployments.

   .. py:method:: test_client(**kwargs) -> httpx.AsyncClient

      Return an ``httpx.AsyncClient`` configured to send requests directly
      to this app.  The returned client must be used as an async context
      manager.

Module-Level Helpers
--------------------

.. py:function:: openviper.app.get_handler_signature(handler)

   Return ``(signature, type_hints)`` for *handler*, cached by identity.
   Bounded by an LRU cache of 128 entries.

.. py:function:: openviper.app.resolve_middleware_entry(mw)

   Import and return a middleware class from a dotted string, or pass through
   a non-string *mw* as-is.  Raises ``ImportError`` if *mw* is a string that
   cannot be imported.

Lifecycle & App Discovery
-------------------------

When the ASGI lifespan starts, the ``OpenViper`` application performs the
following steps in order:

1. Build the middleware stack (cached after first build).
2. Generate the OpenAPI schema (if enabled).
3. Call ``ready()`` on every installed app that exposes one.
4. Call ``startup()`` from installed app ``lifecycle.py`` modules.
5. Run registered ``on_startup`` handlers.

On shutdown the process runs in reverse:

1. Call ``shutdown()`` for started lifecycle apps in reverse order.
2. Run registered ``on_shutdown`` handlers.

Route Auto-Discovery
~~~~~~~~~~~~~~~~~~~~~

If ``OPENVIPER_SETTINGS_MODULE`` is set (e.g. ``"myproject.settings"``),
the application automatically imports ``myproject.routes`` and registers
any ``route_paths`` list found there.  Each entry in ``route_paths`` must
be a ``(prefix, Router)`` tuple.

.. code-block:: python

   # myproject/routes.py
   from openviper.routing.router import Router
   from myapp.views import user_router, order_router

   route_paths = [
       ("/users", user_router),
       ("/orders", order_router),
   ]

Installed App Hooks
~~~~~~~~~~~~~~~~~~~

Each entry in ``settings.INSTALLED_APPS`` may expose a ``ready()`` callable
in one of three locations (checked in order):

1. ``<app>.ready`` - a top-level attribute on the app package.
2. ``<app>.apps.ready`` - inside an ``apps`` sub-module.
3. ``<app>.lifecycle.ready`` - inside a ``lifecycle`` sub-module.

The callable may be either a plain function or an ``async`` coroutine.

Middleware Stack
---------------

The middleware stack is built from ``settings.MIDDLEWARE`` plus any extra
middleware passed to the ``OpenViper`` constructor.  String entries are
resolved via :func:`~openviper.app.resolve_middleware_entry`.  The stack is
assembled in this order (outermost first):

1. ``ServerErrorMiddleware`` - catches unhandled exceptions.
2. ``DefaultLandingMiddleware`` - serves the landing page when no custom
   root route exists.
3. User-configured middleware from ``settings.MIDDLEWARE``.
4. ``RateLimitMiddleware`` - prepended when ``RATE_LIMIT_REQUESTS > 0``.
5. Static and media file serving (debug mode only).

When ``CORSMiddleware`` is present in the middleware list, its keyword
arguments are automatically wired from the ``CORS_*`` settings.

Response Coercion
-----------------

Handlers do not need to return a
:class:`~openviper.http.response.Response` explicitly.  The
:meth:`OpenViper.coerce_response` method converts common return types
automatically:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Return Type
     - Response
   * - ``dict`` or ``list``
     - :class:`~openviper.http.response.JSONResponse`
   * - ``str`` or ``bytes``
     - :class:`~openviper.http.response.PlainTextResponse`
   * - ``None``
     - ``Response(status_code=204)``
   * - Pydantic ``BaseModel``
     - :class:`~openviper.http.response.JSONResponse` via ``model_dump()``
   * - Object with ``model_dump()``
     - :class:`~openviper.http.response.JSONResponse` via ``model_dump()``
   * - :class:`~openviper.http.response.Response`
     - Passed through unchanged

Exception Handling
------------------

Unhandled exceptions are dispatched to the most specific registered handler
by walking the exception's MRO.  Built-in handling is provided for:

- :class:`~openviper.exceptions.HTTPException` - returns the status code and
  detail from the exception.
- :class:`~openviper.exceptions.TableNotFound` - returns 503; hides the
  table name in production.
- :class:`~openviper.exceptions.FieldError` /
  :class:`~openviper.exceptions.QueryError` - returns 400; hides field names
  in production.
- All other exceptions - returns 500 with a debug traceback in debug mode,
  or a generic ``"Internal Server Error"`` in production.

Custom exception handlers are registered with the
:meth:`~openviper.app.OpenViper.exception_handler` decorator.

Append-Slash Redirects
----------------------

In production mode (``DEBUG=False``), if a request path without a trailing
slash does not match any route but the slash-appended path does, the
application returns a ``301`` redirect.  The redirect target is validated
to prevent open-redirect attacks: directory traversal sequences (``..``)
and non-relative paths are rejected.

API Reference
-------------

.. py:module:: openviper.app

.. py:data:: HAS_PYDANTIC

   ``True`` when the ``pydantic`` package is importable; ``False`` otherwise.
   Used by :meth:`coerce_response` to detect Pydantic model instances.
