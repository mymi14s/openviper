"""
OpenViper - A production-ready, high-performance Python web framework,
with modern async capabilities.
"""

import importlib
import sys

from openviper.conf import settings
from openviper.version import __version__ as __version__

LAZY_SUBPACKAGES: dict[str, str] = {
    "ai": "openviper.ai",
    "admin": "openviper.admin",
    "staticfiles": "openviper.staticfiles",
    "tasks": "openviper.tasks",
}

LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "OpenViper": ("openviper.app", "OpenViper"),
    "Request": ("openviper.http.request", "Request"),
    "Response": ("openviper.http.response", "Response"),
    "JSONResponse": ("openviper.http.response", "JSONResponse"),
    "HTMLResponse": ("openviper.http.response", "HTMLResponse"),
    "RedirectResponse": ("openviper.http.response", "RedirectResponse"),
    "StreamingResponse": ("openviper.http.response", "StreamingResponse"),
    "FileResponse": ("openviper.http.response", "FileResponse"),
    "Router": ("openviper.routing.router", "Router"),
    "include": ("openviper.routing.router", "include"),
    "OpenViperException": ("openviper.exceptions", "OpenViperException"),
    "HTTPException": ("openviper.exceptions", "HTTPException"),
    "NotFound": ("openviper.exceptions", "NotFound"),
    "PermissionDenied": ("openviper.exceptions", "PermissionDenied"),
    "ValidationError": ("openviper.exceptions", "ValidationError"),
}


def __getattr__(name: str) -> object:
    """Lazily import public modules only when they are accessed."""
    if name in LAZY_SUBPACKAGES:
        module = importlib.import_module(LAZY_SUBPACKAGES[name])
        setattr(sys.modules[__name__], name, module)
        return module
    if name in LAZY_EXPORTS:
        module_path, attr_name = LAZY_EXPORTS[name]
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        setattr(sys.modules[__name__], name, value)
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def setup(force: bool = False) -> None:
    """Initialize framework settings and registry.

    Triggers lazy settings resolution when *force* is ``True``,
    reloading from ``OPENVIPER_SETTINGS_MODULE`` regardless of prior
    configuration state.
    """
    settings.setup(force=force)


__all__ = [
    "OpenViper",
    "Request",
    "Response",
    "JSONResponse",
    "HTMLResponse",
    "RedirectResponse",
    "StreamingResponse",
    "FileResponse",
    "Router",
    "include",
    "OpenViperException",
    "HTTPException",
    "NotFound",
    "PermissionDenied",
    "ValidationError",
    "__version__",
    "setup",
]
