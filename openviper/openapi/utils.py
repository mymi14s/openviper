"""Utility helpers for the OpenAPI module.

Re-exports the public helpers so callers can import from a single, stable
location without depending on internal module structure.
"""

from __future__ import annotations

from openviper.openapi.router import should_register_openapi
from openviper.openapi.schema import filter_openapi_routes

__all__ = [
    "filter_openapi_routes",
    "should_register_openapi",
]
