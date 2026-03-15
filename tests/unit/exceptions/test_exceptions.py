"""Unit tests for openviper/exceptions.py."""

from __future__ import annotations

import pytest

from openviper.exceptions import (
    AIException,
    AuthenticationFailed,
    Conflict,
    DoesNotExist,
    FieldError,
    HTTPException,
    ImproperlyConfigured,
    IntegrityError,
    MethodNotAllowed,
    MiddlewareException,
    MigrationError,
    ModelCollisionError,
    ModelNotFoundError,
    MultipleObjectsReturned,
    NotFound,
    OpenViperException,
    ORMException,
    PermissionDenied,
    ServiceUnavailable,
    SettingsValidationError,
    TokenExpired,
    TooManyRequests,
    Unauthorized,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_http_exc(status: int = 400, detail: str | None = None) -> HTTPException:
    return HTTPException(status, detail)


def make_model_not_found(
    model: str = "gpt-4", available: list[str] | None = None
) -> ModelNotFoundError:
    return ModelNotFoundError(model, available)


def make_collision(
    model: str = "gpt-4", existing: str = "OpenAI", new: str = "Azure"
) -> ModelCollisionError:
    return ModelCollisionError(model, existing, new)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_openviper_exception_is_base(self):
        assert issubclass(OpenViperException, Exception)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ImproperlyConfigured,
            SettingsValidationError,
            ORMException,
            MigrationError,
            AIException,
            MiddlewareException,
        ],
    )
    def test_direct_subclasses(self, exc_cls):
        assert issubclass(exc_cls, OpenViperException)

    def test_http_exception_is_openviper(self):
        assert issubclass(HTTPException, OpenViperException)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            NotFound,
            MethodNotAllowed,
            PermissionDenied,
            Unauthorized,
            ValidationError,
            Conflict,
            TooManyRequests,
            ServiceUnavailable,
            AuthenticationFailed,
        ],
    )
    def test_http_subclasses(self, exc_cls):
        assert issubclass(exc_cls, HTTPException)

    def test_token_expired_is_auth_failed(self):
        assert issubclass(TokenExpired, AuthenticationFailed)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            DoesNotExist,
            MultipleObjectsReturned,
            IntegrityError,
            FieldError,
        ],
    )
    def test_orm_subclasses(self, exc_cls):
        assert issubclass(exc_cls, ORMException)

    @pytest.mark.parametrize("exc_cls", [ModelNotFoundError, ModelCollisionError])
    def test_ai_subclasses(self, exc_cls):
        assert issubclass(exc_cls, AIException)


# ---------------------------------------------------------------------------
# HTTPException
# ---------------------------------------------------------------------------


class TestHTTPException:
    @pytest.mark.parametrize(
        ("status", "detail"),
        [
            (400, "Bad Request"),
            (404, "Not found"),
            (500, "Server error"),
        ],
    )
    def test_stores_status_and_detail(self, status, detail):
        exc = make_http_exc(status, detail)
        assert exc.status_code == status
        assert exc.detail == detail

    def test_default_detail_uses_http_phrase(self):
        assert "Not Found" in HTTPException(404).detail

    def test_unknown_status_fallback(self):
        assert HTTPException(999).detail == "Error"

    def test_headers_default_empty(self):
        assert HTTPException(400).headers == {}

    def test_headers_stored(self):
        exc = HTTPException(400, headers={"X-Custom": "v"})
        assert exc.headers["X-Custom"] == "v"

    def test_str_has_status(self):
        assert "404" in str(HTTPException(404, "oops"))


class TestNotFound:
    def test_status(self):
        assert NotFound().status_code == 404

    def test_default_detail(self):
        assert "not found" in NotFound().detail.lower()

    def test_custom_detail(self):
        assert NotFound("gone").detail == "gone"

    def test_with_headers(self):
        exc = NotFound(headers={"X-A": "1"})
        assert exc.headers.get("X-A") == "1"


class TestMethodNotAllowed:
    def test_status(self):
        assert MethodNotAllowed(["GET"]).status_code == 405

    def test_allow_header(self):
        exc = MethodNotAllowed(["GET", "POST"])
        assert "GET" in exc.headers["Allow"]
        assert "POST" in exc.headers["Allow"]


class TestPermissionDenied:
    def test_status(self):
        assert PermissionDenied().status_code == 403

    def test_custom_detail(self):
        assert PermissionDenied("No access").detail == "No access"


class TestUnauthorized:
    def test_status(self):
        assert Unauthorized().status_code == 401

    def test_www_authenticate(self):
        assert "Bearer" in Unauthorized().headers["WWW-Authenticate"]


class TestValidationError:
    def test_status(self):
        assert ValidationError([]).status_code == 422

    def test_stores_errors(self):
        errs = [{"field": "x", "message": "required"}]
        exc = ValidationError(errs)
        assert exc.validation_errors == errs


class TestConflict:
    def test_status(self):
        assert Conflict().status_code == 409


class TestTooManyRequests:
    def test_status(self):
        assert TooManyRequests().status_code == 429

    def test_retry_after(self):
        assert TooManyRequests(retry_after=30).headers["Retry-After"] == "30"

    def test_no_retry_after_when_none(self):
        assert "Retry-After" not in TooManyRequests().headers

    def test_custom_detail(self):
        assert TooManyRequests(detail="slow").detail == "slow"


class TestServiceUnavailable:
    def test_status(self):
        assert ServiceUnavailable().status_code == 503


class TestAuthenticationFailed:
    def test_status(self):
        assert AuthenticationFailed().status_code == 401

    def test_bearer_header(self):
        assert "Bearer" in AuthenticationFailed().headers["WWW-Authenticate"]

    def test_custom_detail(self):
        assert AuthenticationFailed("bad creds").detail == "bad creds"


class TestTokenExpired:
    def test_inherits_auth_failed(self):
        assert isinstance(TokenExpired(), AuthenticationFailed)

    def test_message(self):
        assert "expired" in TokenExpired().detail.lower()


class TestORMExceptions:
    @pytest.mark.parametrize(
        "exc_cls",
        [
            DoesNotExist,
            MultipleObjectsReturned,
            IntegrityError,
            FieldError,
        ],
    )
    def test_can_raise_and_catch(self, exc_cls):
        with pytest.raises(exc_cls):
            raise exc_cls("boom")

    def test_migration_error_message(self):
        exc = MigrationError("bad migration")
        assert "bad migration" in str(exc)


class TestSettingsValidationError:
    def test_stores_errors(self):
        errs = ["err1", "err2"]
        exc = SettingsValidationError(errs)
        assert exc.errors == errs

    def test_message_contains_all(self):
        errs = ["A", "B"]
        msg = str(SettingsValidationError(errs))
        assert "A" in msg
        assert "B" in msg


class TestModelNotFoundError:
    def test_model_stored(self):
        assert make_model_not_found("gpt-4").model == "gpt-4"

    def test_available_defaults_empty(self):
        assert make_model_not_found("gpt-4").available == []

    def test_available_in_message(self):
        exc = ModelNotFoundError("m", ["a", "b"])
        assert "a" in str(exc)

    def test_available_stored(self):
        exc = ModelNotFoundError("m", ["a", "b"])
        assert exc.available == ["a", "b"]


class TestModelCollisionError:
    def test_attributes_stored(self):
        exc = make_collision()
        assert exc.model == "gpt-4"
        assert exc.existing_provider == "OpenAI"
        assert exc.new_provider == "Azure"

    def test_message_parts(self):
        exc = make_collision("gpt-4", "OpenAI", "Azure")
        msg = str(exc)
        assert "gpt-4" in msg
        assert "OpenAI" in msg
        assert "Azure" in msg

    def test_middleware_exception(self):
        exc = MiddlewareException("mw error")
        assert isinstance(exc, OpenViperException)
