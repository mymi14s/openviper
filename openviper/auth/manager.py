"""Authentication manager for OpenViper.

The :class:`AuthManager` iterates over a configurable list of authentication
backends and returns the first successfully authenticated user.  The default
backends are :class:`~openviper.auth.backends.jwt_backend.JWTBackend` followed
by :class:`~openviper.auth.backends.session_backend.SessionBackend`.

Configuration::

    # In your settings module
    AUTH_BACKENDS = (
        "openviper.auth.backends.jwt_backend.JWTBackend",
        "openviper.auth.backends.session_backend.SessionBackend",
    )
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from openviper.auth.models import AnonymousUser
from openviper.conf import settings

logger = logging.getLogger("openviper.auth.manager")

_DEFAULT_BACKENDS: tuple[str, ...] = (
    "openviper.auth.backends.jwt_backend.JWTBackend",
    "openviper.auth.backends.session_backend.SessionBackend",
)


def _load_backend(dotted_path: str) -> Any:
    """Import and instantiate a backend class from its dotted path.

    Args:
        dotted_path: Fully-qualified class path, e.g.
            ``"openviper.auth.backends.jwt_backend.JWTBackend"``.

    Returns:
        An instantiated backend object.
    """
    module_path, _, class_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


class AuthManager:
    """Manages a list of authentication backends.

    Iterates over configured backends in order and returns the first
    successfully authenticated ``(user, auth_info)`` pair.  Falls back to
    :class:`~openviper.auth.models.AnonymousUser` if no backend succeeds.

    Args:
        backends: Optional list of pre-instantiated backend objects.  When
            ``None`` (the default) the list is built from the ``AUTH_BACKENDS``
            setting, falling back to :data:`_DEFAULT_BACKENDS`.

    Example::

        manager = AuthManager()
        user, auth_info = await manager.authenticate(scope)
    """

    def __init__(self, backends: list[Any] | None = None) -> None:
        if backends is not None:
            self._backends = backends
        else:
            self._backends = self._load_configured_backends()

    def _load_configured_backends(self) -> list[Any]:
        """Instantiate backends from the ``AUTH_BACKENDS`` setting."""
        backend_paths = getattr(settings, "AUTH_BACKENDS", _DEFAULT_BACKENDS)
        result: list[Any] = []
        for path in backend_paths:
            try:
                result.append(_load_backend(path))
            except Exception as exc:
                logger.warning("Failed to load auth backend %r: %s", path, exc)
        return result

    async def authenticate(self, scope: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        """Try each backend and return the first authenticated user.

        Args:
            scope: ASGI connection scope passed to each backend's
                ``authenticate()`` method.

        Returns:
            ``(user, auth_info)`` where ``user`` is
            :class:`~openviper.auth.models.AnonymousUser` and
            ``auth_info`` is ``{"type": "none"}`` if no backend succeeds.
        """
        for backend in self._backends:
            try:
                result = await backend.authenticate(scope)
                if result is not None:
                    user, auth_info = result
                    if user and getattr(user, "is_active", True):
                        return user, auth_info
            except Exception as exc:
                logger.warning("Auth backend %r raised: %s", backend, exc)

        return AnonymousUser(), {"type": "none"}
