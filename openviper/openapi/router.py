"""OpenAPI router registration guard.

Provides :func:`should_register_openapi` which centralises the logic for
deciding whether the OpenAPI docs router should be registered at all.

When ``settings.OPENAPI["exclude"] == "__ALL__"`` the router is disabled
entirely; the docs, schema, and ReDoc endpoints will not be registered and
will return 404.  Any other value (including an empty list) leaves the
router active.
"""

from __future__ import annotations

import logging

from openviper.conf import settings

logger = logging.getLogger(__name__)

DISABLE_ALL: str = "__ALL__"


def read_openapi_settings() -> dict[str, object]:
    """Read and normalise the OPENAPI config dict from settings."""
    try:
        cfg = dict(getattr(settings, "OPENAPI", {}) or {})
    except (AttributeError, TypeError, ValueError):
        return {}

    # Fill defaults for keys not supplied by the caller.
    defaults: dict[str, object] = {
        "title": "OpenViper API",
        "version": "0.0.1",
        "description": "",
        "docs_url": "/open-api/docs",
        "redoc_url": "/open-api/redoc",
        "schema_url": "/open-api/openapi.json",
        "enabled": True,
        "admin_url": None,
        "exclude": [],
    }
    for key, default in defaults.items():
        cfg.setdefault(key, default)

    return cfg


def should_register_openapi() -> bool:
    """Return ``True`` when the OpenAPI router should be registered.

    The router is skipped when **either** of the following is true:

    * ``OPENAPI["enabled"]`` is ``False``
    * ``OPENAPI["exclude"]`` is the sentinel string ``"__ALL__"``

    All other values of ``exclude`` (list or empty) leave the router
    active - route-level filtering is applied at schema-generation time
    via :func:`openviper.openapi.schema.filter_openapi_routes`.
    """
    cfg = read_openapi_settings()

    if not bool(cfg.get("enabled", True)):
        return False

    exclude = cfg.get("exclude", [])
    if exclude == DISABLE_ALL:
        logger.debug("OPENAPI exclude='__ALL__': router registration skipped.")
        return False

    return True
