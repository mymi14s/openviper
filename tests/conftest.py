"""Shared pytest fixtures and configuration for the OpenViper test suite."""

from __future__ import annotations

import sys

# Ensure the openviper package is importable from the repo root
sys.path.insert(0, "/home/claude")

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
