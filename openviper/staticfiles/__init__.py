"""OpenViper static files serving.

Exposes ``static()`` and ``media()`` registration helpers that signal the
framework to attach ``StaticFilesMiddleware`` when ``DEBUG=True``.
In production (``DEBUG=False``), no static or media serving is configured here.
"""

import threading

from openviper.staticfiles.handlers import StaticFilesMiddleware, collect_static

# Thread-safe flags - set by calling static() / media() in routes.py.
static_serving_enabled: threading.Event = threading.Event()
media_serving_enabled: threading.Event = threading.Event()


def static() -> list[str]:
    """Signal the framework to enable static file serving.

    Sets ``static_serving_enabled``.  Returns an empty list so it can be
    concatenated to ``route_paths`` without error.  The ``DEBUG`` check is
    handled in ``app.py``, not here.
    """
    static_serving_enabled.set()
    return []


def is_static_enabled() -> bool:
    """Return True if static() has been called (i.e. the user opted in)."""
    return static_serving_enabled.is_set()


def media() -> list[str]:
    """Signal the framework to enable media file serving.

    Sets ``media_serving_enabled``.  Returns an empty list so it can be
    concatenated to ``route_paths`` without error.  The ``DEBUG`` check is
    handled in ``app.py``, not here.
    """
    media_serving_enabled.set()
    return []


def is_media_enabled() -> bool:
    """Return True if media() has been called."""
    return media_serving_enabled.is_set()


__all__ = [
    "StaticFilesMiddleware",
    "collect_static",
    "is_media_enabled",
    "is_static_enabled",
    "media",
    "static",
]
