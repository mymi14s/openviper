.. _contrib:

Contrib
=======

The ``openviper.contrib`` package ships optional, batteries-included extras
that are automatically used by the framework in certain modes but can also be
extended or replaced by application code.

Overview
--------

Currently ``openviper.contrib`` contains one sub-package:

``openviper.contrib.default``
    The default landing page and its ASGI middleware, shown in ``DEBUG`` mode
    when no custom route is registered for ``/``.

Key Classes & Functions
-----------------------

``openviper.contrib.default.middleware``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: DefaultLandingMiddleware(app, debug=False, version="0.0.2")

   ASGI middleware that intercepts ``GET /`` when no user-defined route
   exists for the root path.

   - In **debug mode** (``debug=True``): returns a rich HTML welcome page
     showing the OpenViper version, installed apps, and quick-start links.
   - In **production** (``debug=False``): returns a standard ``404 Not Found``
     response.

   This middleware is registered automatically by
   :class:`~openviper.app.OpenViper`; you do not need to add it manually.

``openviper.contrib.default.landing``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:data:: LANDING_HTML

   The HTML string for the welcome page.  It is a self-contained, styled
   page with no external dependencies.

Example Usage
-------------

The middleware is enabled automatically when no ``/`` route is registered:

.. code-block:: python

    from openviper import OpenViper

    app = OpenViper(title="My API", version="1.0.0")

    # No route for "/" defined — visiting http://localhost:8000/ in DEBUG mode
    # will show the OpenViper welcome page.

Replacing the Default Landing Page
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Register your own ``/`` route to override the default:

.. code-block:: python

    from openviper import OpenViper
    from openviper.http.response import HTMLResponse, JSONResponse

    app = OpenViper()

    @app.get("/")
    async def home(request) -> JSONResponse:
        return JSONResponse({"message": "Welcome to My API"})

    # Now the default landing middleware is bypassed for GET /

Custom Welcome Page
~~~~~~~~~~~~~~~~~~~~

If you want a custom debug page, subclass or wrap
:class:`~openviper.contrib.default.middleware.DefaultLandingMiddleware`:

.. code-block:: python

    from openviper.contrib.default.middleware import DefaultLandingMiddleware
    from openviper.http.response import HTMLResponse

    class MyLandingMiddleware(DefaultLandingMiddleware):
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] == "http" and scope["path"] == "/":
                response = HTMLResponse("<h1>My Custom Welcome Page</h1>")
                await response(scope, receive, send)
            else:
                await self.app(scope, receive, send)
