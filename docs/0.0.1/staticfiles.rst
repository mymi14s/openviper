.. _staticfiles:

Static Files
============

The ``openviper.staticfiles`` package provides development-time static file
serving and a ``collectstatic`` utility for production builds.

Overview
--------

In development (``DEBUG=True``), static files are served directly by the
framework via :class:`~openviper.staticfiles.StaticFilesMiddleware`.  In
production (``DEBUG=False``), static files should be served by a reverse
proxy such as nginx; the middleware is not mounted.

Call :func:`static` and/or :func:`media` in ``routes.py`` to opt in to
framework-managed serving:

.. code-block:: python

    # routes.py
    from openviper.staticfiles import static, media

    route_paths = [
        ("/", main_router),
        ("/admin", get_admin_site()),
    ] + static() + media()

Key Classes & Functions
-----------------------

.. py:class:: openviper.staticfiles.StaticFilesMiddleware(app, url_path="/static", directories=None)

   ASGI middleware that intercepts requests whose path starts with *url_path*
   and serves the matching file from one of the *directories*.

   - ``url_path`` — URL prefix to intercept (default: ``"/static"``).
   - ``directories`` — list of filesystem directories to search.
     Defaults to ``["static"]``.

   Supports ``If-None-Match`` (304 Not Modified), correct MIME type
   detection, and ``Content-Length`` headers.

.. py:function:: openviper.staticfiles.static() -> list

   Signal the framework to enable static file serving at ``STATIC_URL``.
   Returns an empty list so it can be appended safely to ``route_paths``.

.. py:function:: openviper.staticfiles.media() -> list

   Signal the framework to enable media file serving at ``MEDIA_URL``.
   Returns an empty list so it can be appended safely to ``route_paths``.

.. py:function:: openviper.staticfiles.collect_static(source_dirs=None, dest_dir=None) -> None

   Copy all static files from *source_dirs* (including per-app ``static/``
   directories) into *dest_dir* (defaults to ``settings.STATIC_ROOT``).
   Intended for production CI pipelines.

Example Usage
-------------

Development Static Serving
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # routes.py
    from openviper.routing.router import Router
    from openviper.staticfiles import static, media

    router = Router()

    @router.get("/")
    async def home(request): ...

    route_paths = [
        ("/", router),
    ] + static() + media()

Now ``/static/app.js`` resolves to ``<project_root>/static/app.js`` and
``/media/uploads/photo.jpg`` resolves to ``<MEDIA_ROOT>/uploads/photo.jpg``
when ``DEBUG=True``.

Direct Middleware Usage
~~~~~~~~~~~~~~~~~~~~~~~

Attach the middleware manually when you need custom URL paths or multiple
static directories:

.. code-block:: python

    from openviper import OpenViper
    from openviper.staticfiles import StaticFilesMiddleware

    app = OpenViper()
    app = StaticFilesMiddleware(
        app,
        url_path="/assets",
        directories=["static", "frontend/dist"],
    )

Collecting Static Files for Production
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    openviper viperctl collectstatic .

Or call it programmatically:

.. code-block:: python

    from openviper.staticfiles.handlers import collect_static

    collect_static(
        source_dirs=["static", "myapp/static"],
        dest_dir="public/static",
    )

Configuration
-------------

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        STATIC_URL: str = "/static/"
        STATIC_ROOT: str = "staticfiles"
        MEDIA_URL: str = "/media/"
        MEDIA_ROOT: str = "media"
