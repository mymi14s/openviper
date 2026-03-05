"""OpenViper static files serving.

Usage in routes.py (Django-like pattern)::

    from openviper.staticfiles import static

    route_paths = [
        ("/", router),
        ("/admin", get_admin_site()),
    ] + static()

When ``static()`` is called, the framework automatically wraps the ASGI app
in ``StaticFilesMiddleware`` for ``DEBUG=True`` (development).  In production
(``DEBUG=False``) no static serving is configured here — use nginx or a CDN.
"""

from openviper.staticfiles.handlers import StaticFilesMiddleware, collect_static
from typing import Any

# Internal flags — set by calling static() / media() in routes.py
_static_serving_enabled: bool = False
_media_serving_enabled: bool = False


def static() -> list[Any]:
    """Enable framework static file serving in DEBUG mode.

    Call this in your ``route_paths`` (or anywhere at import time) to signal
    the framework that it should serve ``/static/**`` automatically when
    ``settings.DEBUG`` is ``True``.

    Returns an empty list so it can safely be appended to ``route_paths``::

        route_paths = [
            ("/", router),
        ] + static()

    In production (``DEBUG=False``) this is a no-op — static files should be
    served by an external reverse proxy such as nginx.
    """
    global _static_serving_enabled
    _static_serving_enabled = True
    return []  # empty — adds nothing to route_paths, just sets the flag


def is_static_enabled() -> bool:
    """Return True if static() has been called (i.e. the user opted in)."""
    return _static_serving_enabled


def media() -> list[Any]:
    """Enable framework media file serving in DEBUG mode.

    Call this in your ``route_paths`` to serve user-uploaded files at
    ``MEDIA_URL`` from ``MEDIA_ROOT`` when ``settings.DEBUG`` is ``True``::

        route_paths = [
            ("/", router),
        ] + static() + media()

    In production (``DEBUG=False``) this is a no-op — media files should be
    served by nginx directly from the media volume.
    """
    global _media_serving_enabled
    _media_serving_enabled = True
    return []


def is_media_enabled() -> bool:
    """Return True if media() has been called."""
    return _media_serving_enabled


__all__ = [
    "StaticFilesMiddleware",
    "collect_static",
    "static",
    "media",
    "is_static_enabled",
    "is_media_enabled",
]
