"""OpenViper exception hierarchy.

All framework exceptions live here.  AI-specific exceptions extend
:class:`AIException` which is a subclass of :class:`OpenViperException` so
callers can catch either the broad base or the narrow AI-specific variant.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class OpenViperException(Exception):
    """Base exception for all OpenViper errors."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Configuration & Settings
# ---------------------------------------------------------------------------


class ImproperlyConfigured(OpenViperException):
    """Framework or application is incorrectly configured."""

    __slots__ = ()


class SettingsValidationError(OpenViperException):
    """Settings failed validation on startup."""

    __slots__ = ("errors",)

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(f"  - {e}" for e in errors))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class HTTPException(OpenViperException):
    """Raised to return an HTTP error response.

    Args:
        status_code: HTTP status code.
        detail: Human-readable error detail.
        headers: Optional extra headers to include in the response.
    """

    __slots__ = ("status_code", "detail", "headers")

    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail if detail is not None else self._default_detail()
        self.headers = headers or {}
        super().__init__(f"HTTP {status_code}: {self.detail}")

    def _default_detail(self) -> str:
        try:
            return HTTPStatus(self.status_code).phrase
        except ValueError:
            return "Error"


class NotFound(HTTPException):
    """404 Not Found."""

    __slots__ = ()

    def __init__(self, detail: str = "Not found.", headers: dict[str, str] | None = None) -> None:
        super().__init__(404, detail, headers)


class MethodNotAllowed(HTTPException):
    """405 Method Not Allowed."""

    __slots__ = ()

    def __init__(self, allowed: list[str]) -> None:
        super().__init__(
            405,
            "Method not allowed.",
            {"Allow": ", ".join(allowed)},
        )


class PermissionDenied(HTTPException):
    """403 Forbidden."""

    __slots__ = ()

    def __init__(self, detail: str = "Permission denied.") -> None:
        super().__init__(403, detail)


class Unauthorized(HTTPException):
    """401 Unauthorized."""

    __slots__ = ()

    def __init__(self, detail: str = "Authentication required.") -> None:
        super().__init__(401, detail, {"WWW-Authenticate": "Bearer"})


class ValidationError(HTTPException):
    """422 Unprocessable Entity — request body / parameter validation failure."""

    __slots__ = ("validation_errors",)

    def __init__(self, errors: Any) -> None:
        self.validation_errors = errors
        super().__init__(422, errors)


class Conflict(HTTPException):
    """409 Conflict."""

    __slots__ = ()

    def __init__(self, detail: str = "Conflict.") -> None:
        super().__init__(409, detail)


class TooManyRequests(HTTPException):
    """429 Too Many Requests."""

    __slots__ = ()

    def __init__(self, retry_after: int | None = None, detail: str | None = None) -> None:
        headers: dict[str, str] = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        super().__init__(429, detail or "Too many requests.", headers)


class ServiceUnavailable(HTTPException):
    """503 Service Unavailable."""

    __slots__ = ()

    def __init__(self, detail: str = "Service unavailable.") -> None:
        super().__init__(503, detail)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class AuthenticationFailed(HTTPException):
    """Authentication attempt failed."""

    __slots__ = ()

    def __init__(self, detail: str = "Invalid credentials.") -> None:
        super().__init__(401, detail, {"WWW-Authenticate": "Bearer"})


class TokenExpired(AuthenticationFailed):
    """JWT or session token has expired."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("Token has expired.")


# ---------------------------------------------------------------------------
# ORM / Database
# ---------------------------------------------------------------------------


class ORMException(OpenViperException):
    """Base ORM error."""

    __slots__ = ()


class DoesNotExist(ORMException):
    """Record not found."""

    __slots__ = ()


class MultipleObjectsReturned(ORMException):
    """Query returned more than one record when exactly one was expected."""

    __slots__ = ()


class IntegrityError(ORMException):
    """Database integrity constraint violated."""

    __slots__ = ()


class MigrationError(OpenViperException):
    """Migration could not be applied or reversed."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class MiddlewareException(OpenViperException):
    """Error raised within the middleware pipeline."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# AI subsystem
# ---------------------------------------------------------------------------


class AIException(OpenViperException):
    """Base exception for all OpenViper AI errors."""

    __slots__ = ()


class ModelNotFoundError(AIException):
    """Raised when a requested model ID is not registered in the ProviderRegistry."""

    __slots__ = ("model", "available")

    def __init__(self, model: str, available: list[str] | None = None) -> None:
        msg = f"Model '{model}' is not registered."
        if available:
            msg += f" Available models: {available}"
        super().__init__(msg)
        self.model = model
        self.available = available or []


class ModelCollisionError(AIException):
    """Raised when a model ID is already registered and ``allow_override=False``."""

    __slots__ = ("model", "existing_provider", "new_provider")

    def __init__(self, model: str, existing_provider: str, new_provider: str) -> None:
        super().__init__(
            f"Model '{model}' is already registered to provider '{existing_provider}'. "
            f"Provider '{new_provider}' attempted to claim the same model ID. "
            "Pass allow_override=True to replace the existing registration."
        )
        self.model = model
        self.existing_provider = existing_provider
        self.new_provider = new_provider
