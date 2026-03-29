.. _plugins:

Plugin Development
==================

OpenViper is designed so that third-party packages can extend it cleanly without
modifying framework code.  A "plugin" is simply a Python package that hooks into
the framework through one or more of the mechanisms described below.

.. contents::
   :local:
   :depth: 2

----

The ``ready()`` Hook
--------------------

Every package listed in ``settings.INSTALLED_APPS`` may expose an async (or
sync) ``ready()`` callable.  OpenViper calls it automatically during the ASGI
**lifespan startup** event — before any HTTP request is processed and before
user-registered ``@app.on_startup`` handlers run.

This is the primary entry-point for plugin initialisation: registering signals,
connecting to external services, warming caches, or doing any other async setup
work that cannot be done at import time.

Where to define ``ready()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenViper looks in two places, in order:

1. **Top-level package attribute** — define ``ready`` in your package's
   ``__init__.py``:

   .. code-block:: python

       # myplugin/__init__.py
       async def ready() -> None:
           await connect_to_broker()
           await warm_cache()

2. **``apps`` sub-module** — define ``ready`` in ``myplugin/apps.py`` (useful
   when you want to keep startup logic separate from the public API):

   .. code-block:: python

       # myplugin/apps.py
       async def ready() -> None:
           await register_event_handlers()

If both exist, the top-level ``__init__.py`` version takes precedence.

Sync ``ready()`` is also supported
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The callable may be a plain function if you have no async setup to perform:

.. code-block:: python

    # myplugin/__init__.py
    def ready() -> None:
        register_admin_panels()
        register_serializer_fields()

Registering the plugin
~~~~~~~~~~~~~~~~~~~~~~

Add the package name to ``INSTALLED_APPS`` in your project settings:

.. code-block:: python

    # myproject/settings.py
    from openviper.conf import BaseSettings

    class Settings(BaseSettings):
        INSTALLED_APPS: tuple[str, ...] = (
            "openviper.auth",
            "myplugin",
            "myproject.users",
        )

``ready()`` is called once per startup, in the order the apps are listed.

Error handling
~~~~~~~~~~~~~~

If ``ready()`` raises an exception the startup **fails immediately** and the
server will not accept requests.  The error message includes the app label so
the source is easy to identify:

.. code-block:: text

    RuntimeError: ready() for installed app 'myplugin' raised an error: ...

Unimportable apps (packages that cannot be found) log a warning and are skipped
rather than crashing the server.

----

Middleware-based plugins
------------------------

Plugins that need to intercept every request — or that need to handle
non-HTTP scopes such as lifespan events — should be implemented as
:ref:`middleware`.

Add the middleware class to ``settings.MIDDLEWARE`` using its dotted import
path:

.. code-block:: python

    class Settings(BaseSettings):
        MIDDLEWARE: tuple[str, ...] = (
            "openviper.middleware.security.SecurityMiddleware",
            "openviper.middleware.cors.CORSMiddleware",
            "myplugin.middleware.MyPluginMiddleware",  # plugin middleware
        )

Middleware runs for **every** request scope (HTTP, lifespan, and any future
scope types).  Pass non-HTTP scopes straight through unless your plugin
specifically handles them:

.. code-block:: python

    from openviper.middleware.base import BaseMiddleware

    class MyPluginMiddleware(BaseMiddleware):
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            # ... plugin logic for HTTP requests
            await self.app(scope, receive, send)

Combining ``ready()`` with middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A common pattern is to perform async initialisation in ``ready()`` and keep
request-time state in a middleware:

.. code-block:: python

    # myplugin/__init__.py
    from myplugin.client import ServiceClient

    _client: ServiceClient | None = None

    async def ready() -> None:
        global _client
        _client = await ServiceClient.connect()

    def get_client() -> ServiceClient:
        if _client is None:
            raise RuntimeError("Plugin not ready — is it in INSTALLED_APPS?")
        return _client

.. code-block:: python

    # myplugin/middleware.py
    from openviper.middleware.base import BaseMiddleware
    from myplugin import get_client

    class MyPluginMiddleware(BaseMiddleware):
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] == "http":
                scope["my_plugin_client"] = get_client()
            await self.app(scope, receive, send)

----

``INSTALLED_APPS`` auto-discovery
----------------------------------

Beyond ``ready()``, being listed in ``INSTALLED_APPS`` also enables:

* **Admin panels** — ``<app>/admin.py`` is auto-discovered and its registered
  models appear in the Admin UI.
* **Static files** — ``<app>/static/`` is served automatically in debug mode.
* **Database migrations** — the migration executor scans each installed app for
  a ``migrations/`` package.
* **DB event handlers** — the event system allows handlers only from modules
  whose root package is in ``INSTALLED_APPS``.

----

Full plugin example
-------------------

The following is a minimal but complete plugin skeleton:

.. code-block:: text

    myplugin/
    ├── __init__.py      ← exposes ready()
    ├── apps.py          ← optional: alternative location for ready()
    ├── middleware.py    ← optional: request-scope work
    ├── admin.py         ← optional: admin panel registrations
    └── migrations/      ← optional: database migrations

.. code-block:: python

    # myplugin/__init__.py
    from __future__ import annotations

    from myplugin.client import ServiceClient

    _client: ServiceClient | None = None


    async def ready() -> None:
        """Called by OpenViper at server startup."""
        global _client
        _client = await ServiceClient.connect(
            url="https://service.example.com",
        )

.. code-block:: python

    # myplugin/middleware.py
    from __future__ import annotations

    from openviper.middleware.base import BaseMiddleware
    from myplugin import _client


    class MyPluginMiddleware(BaseMiddleware):
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            scope["my_plugin"] = _client
            await self.app(scope, receive, send)

.. code-block:: python

    # myproject/settings.py
    from openviper.conf import BaseSettings


    class Settings(BaseSettings):
        INSTALLED_APPS: tuple[str, ...] = (
            "openviper.auth",
            "myplugin",
        )
        MIDDLEWARE: tuple[str, ...] = (
            "openviper.middleware.security.SecurityMiddleware",
            "openviper.middleware.cors.CORSMiddleware",
            "myplugin.middleware.MyPluginMiddleware",
        )
