"""Authentication backend orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from openviper.auth.models import AnonymousUser
from openviper.conf import settings
from openviper.utils.importlib import import_string

if TYPE_CHECKING:
    from openviper.auth.backends import BaseAuthentication
    from openviper.auth.types import Authenticable

logger = logging.getLogger("openviper.auth.manager")

_DEFAULT_BACKENDS: tuple[str, ...] = (
    "openviper.auth.backends.jwt_backend.JWTBackend",
    "openviper.auth.backends.session_backend.SessionBackend",
)


def load_backend(dotted_path: str) -> BaseAuthentication:
    """Import and instantiate a backend class from its dotted path."""
    cls = import_string(dotted_path)
    return cls()


class AuthManager:
    """Ordered authentication backend pipeline."""

    def __init__(self, backends: list[BaseAuthentication] | None = None) -> None:
        if backends is not None:
            self._backends = backends
        else:
            self._backends = self.load_configured_backends()

    def load_configured_backends(self) -> list[BaseAuthentication]:
        """Instantiate backends from the ``AUTH_BACKENDS`` setting."""
        backend_paths = getattr(settings, "AUTH_BACKENDS", _DEFAULT_BACKENDS)
        result: list[BaseAuthentication] = []
        for path in backend_paths:
            try:
                result.append(load_backend(path))
            except (ImportError, AttributeError, TypeError) as exc:
                logger.warning("Failed to load auth backend %r: %s", path, exc)
        return result

    async def authenticate(self, scope: dict[str, object]) -> tuple[Authenticable, dict[str, str]]:
        """Return the first authenticated user from the backend pipeline."""
        for backend in self._backends:
            try:
                result = await backend.authenticate(scope)
                if result is not None:
                    user, auth_info = result
                    if user and getattr(user, "is_active", True):
                        return user, auth_info
            except (ValueError, KeyError, LookupError, AttributeError) as exc:
                logger.warning("Auth backend %r raised: %s", backend, exc)

        return cast("Authenticable", AnonymousUser()), {"type": "none"}
