"""OpenAPI router registration guard.

Provides :func:`should_register_openapi` which centralises the logic for
deciding whether the OpenAPI docs router should be registered at all.

When ``settings.OPENAPI_EXCLUDE == "__ALL__"`` the router is disabled entirely;
the docs, schema, and ReDoc endpoints will not be registered and will return
404.  Any other value (including an empty list) leaves the router active.
"""

from __future__ import annotations

import logging

from openviper.conf import settings

logger = logging.getLogger(__name__)

_DISABLE_ALL: str = "__ALL__"


def should_register_openapi() -> bool:
    """Return ``True`` when the OpenAPI router should be registered.

    The router is skipped when **either** of the following is true:

    * ``settings.OPENAPI_ENABLED`` is ``False``
    * ``settings.OPENAPI_EXCLUDE`` is the sentinel string ``"__ALL__"``

    All other values of ``OPENAPI_EXCLUDE`` (list or empty) leave the router
    active — route-level filtering is applied at schema-generation time via
    :func:`openviper.openapi.schema.filter_openapi_routes`.
    """
    if not getattr(settings, "OPENAPI_ENABLED", True):
        return False

    exclude = getattr(settings, "OPENAPI_EXCLUDE", [])
    if exclude == _DISABLE_ALL:
        logger.debug("OPENAPI_EXCLUDE='__ALL__': OpenAPI router registration skipped.")
        return False

    return True
