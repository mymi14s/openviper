"""Shared pytest fixtures and configuration for the OpenViper test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the openviper package is importable from the repo root.
# Derived from this file's location so the path is portable across machines.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Remove OPENVIPER_SETTINGS_MODULE if it points to a non-existent module
# (e.g. a project-specific settings module that isn't installed in this env).
settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
if settings_module:
    try:
        __import__(settings_module)
    except ImportError:
        os.environ.pop("OPENVIPER_SETTINGS_MODULE", None)


def make_scope(
    method: str = "GET",
    path: str = "/",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    scheme: str = "http",
    server: tuple[str, int] | None = ("localhost", 8000),
    path_params: dict | None = None,
) -> dict:
    """Build a minimal ASGI HTTP scope dict."""
    return {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "query_string": query_string,
        "headers": headers or [],
        "scheme": scheme,
        "server": server,
        "root_path": "",
        "path_params": path_params or {},
    }


async def empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def collect_send(responses: list):
    """Return an ASGI send callable that appends each message to *responses*."""

    async def send(message):
        responses.append(message)

    return send
