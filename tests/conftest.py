"""Shared pytest fixtures and configuration for the OpenViper test suite."""

from __future__ import annotations

import os
import sys

# Ensure the openviper package is importable from the repo root
sys.path.insert(0, "/home/claude")

# Remove OPENVIPER_SETTINGS_MODULE if it points to a non-existent module
# (e.g. a project-specific settings module that isn't installed in this env).
_settings_module = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
if _settings_module:
    try:
        __import__(_settings_module)
    except ImportError:
        os.environ.pop("OPENVIPER_SETTINGS_MODULE", None)

# ---------------------------------------------------------------------------
# ASGI helpers
# ---------------------------------------------------------------------------


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


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def collect_send(responses: list):
    """Return an ASGI send callable that appends each message to *responses*."""

    async def send(message):
        responses.append(message)

    return send
