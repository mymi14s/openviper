"""OpenViper static files serving.

Exposes ``static()`` and ``media()`` registration helpers that signal the
framework to attach ``StaticFilesMiddleware`` when ``DEBUG=True``.
In production (``DEBUG=False``), no static or media serving is configured here.
"""

from typing import Any

from openviper.staticfiles.handlers import StaticFilesMiddleware, collect_static

# Internal flags — set by calling static() / media() in routes.py
_static_serving_enabled: bool = False
_media_serving_enabled: bool = False


def static() -> list[Any]:
    """Signal the framework to enable static file serving in DEBUG mode.

    Sets ``_static_serving_enabled``.  Returns an empty list so it can be
    concatenated to ``route_paths`` without error.  No-op when ``DEBUG=False``.
    """
    global _static_serving_enabled
    _static_serving_enabled = True
    return []  # empty — adds nothing to route_paths, just sets the flag


def is_static_enabled() -> bool:
    """Return True if static() has been called (i.e. the user opted in)."""
    return _static_serving_enabled


def media() -> list[Any]:
    """Signal the framework to enable media file serving in DEBUG mode.

    Sets ``_media_serving_enabled``.  Returns an empty list so it can be
    concatenated to ``route_paths`` without error.  No-op when ``DEBUG=False``.
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
