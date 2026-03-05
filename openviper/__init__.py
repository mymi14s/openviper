"""
OpenViper - A production-ready, high-performance Python web framework,
with modern async capabilities.
"""

from importlib.metadata import version as _version

from openviper.app import OpenViper
from openviper.exceptions import (
    HTTPException,
    NotFound,
    OpenViperException,
    PermissionDenied,
    ValidationError,
)
from openviper.http.request import Request
from openviper.http.response import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from openviper.routing.router import Router, include

# ---------------------------------------------------------------------------
# PEP 562 lazy sub-package loader
# ---------------------------------------------------------------------------

_LAZY_SUBPACKAGES = {
    "ai": "openviper.ai",
    "admin": "openviper.admin",
    "staticfiles": "openviper.staticfiles",
    "tasks": "openviper.tasks",
}


def __getattr__(name: str):
    """Lazily import heavy sub-packages only when they are accessed."""
    import importlib
    import sys

    if name in _LAZY_SUBPACKAGES:
        module = importlib.import_module(_LAZY_SUBPACKAGES[name])
        setattr(sys.modules[__name__], name, module)
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def setup(force: bool = False) -> None:
    """Initialize Openviper settings and registry explicitly.

    This function should be called before importing any other Openviper
    components that rely on settings.
    """
    from openviper.conf import settings

    settings._setup(force=force)


__version__: str = _version("openviper")
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
