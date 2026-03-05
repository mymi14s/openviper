"""Integration tests for openviper.exceptions."""

from __future__ import annotations

from openviper.exceptions import (
    AuthenticationFailed,
    Conflict,
    DoesNotExist,
    HTTPException,
    ImproperlyConfigured,
    IntegrityError,
    MethodNotAllowed,
    MiddlewareException,
    MigrationError,
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


class TestOpenViperException:
    def test_is_exception(self):
        exc = OpenViperException("base")
        assert isinstance(exc, Exception)


class TestImproperlyConfigured:
    def test_is_openviper_exception(self):
        exc = ImproperlyConfigured("bad config")
        assert isinstance(exc, OpenViperException)


class TestSettingsValidationError:
    def test_stores_errors(self):
        exc = SettingsValidationError(["error1", "error2"])
        assert exc.errors == ["error1", "error2"]

    def test_message_includes_errors(self):
        exc = SettingsValidationError(["missing DB", "bad SECRET_KEY"])
        msg = str(exc)
        assert "missing DB" in msg
        assert "bad SECRET_KEY" in msg


class TestHTTPException:
    def test_status_code_stored(self):
        exc = HTTPException(400, "bad request")
        assert exc.status_code == 400

    def test_detail_stored(self):
        exc = HTTPException(400, "bad request")
        assert exc.detail == "bad request"

    def test_headers_stored(self):
        exc = HTTPException(400, "err", headers={"X-Custom": "value"})
        assert exc.headers["X-Custom"] == "value"

    def test_headers_default_empty(self):
        exc = HTTPException(500, "oops")
        assert exc.headers == {}

    def test_default_detail_from_status(self):
        exc = HTTPException(404)
        assert "Not Found" in exc.detail

    def test_unknown_status_default_detail(self):
        exc = HTTPException(999)
        assert exc.detail == "Error"

    def test_str_contains_status(self):
        exc = HTTPException(404, "not here")
        assert "404" in str(exc)


class TestNotFound:
    def test_status_404(self):
        exc = NotFound()
        assert exc.status_code == 404

    def test_custom_detail(self):
        exc = NotFound("item missing")
        assert exc.detail == "item missing"

    def test_default_detail(self):
        exc = NotFound()
        assert exc.detail == "Not found."

    def test_headers_optional(self):
        exc = NotFound(headers={"X-Foo": "bar"})
        assert exc.headers["X-Foo"] == "bar"


class TestMethodNotAllowed:
    def test_status_405(self):
        exc = MethodNotAllowed(["GET", "POST"])
        assert exc.status_code == 405

    def test_allow_header_set(self):
        exc = MethodNotAllowed(["GET", "POST"])
        assert "Allow" in exc.headers
        assert "GET" in exc.headers["Allow"]


class TestPermissionDenied:
    def test_status_403(self):
        exc = PermissionDenied()
        assert exc.status_code == 403

    def test_custom_detail(self):
        exc = PermissionDenied("not allowed")
        assert exc.detail == "not allowed"


class TestUnauthorized:
    def test_status_401(self):
        exc = Unauthorized()
        assert exc.status_code == 401

    def test_www_authenticate_header(self):
        exc = Unauthorized()
        assert "WWW-Authenticate" in exc.headers


class TestValidationError:
    def test_status_422(self):
        exc = ValidationError(["field required"])
        assert exc.status_code == 422

    def test_validation_errors_stored(self):
        errors = [{"field": "email", "message": "invalid"}]
        exc = ValidationError(errors)
        assert exc.validation_errors == errors


class TestConflict:
    def test_status_409(self):
        exc = Conflict()
        assert exc.status_code == 409

    def test_custom_detail(self):
        exc = Conflict("already exists")
        assert exc.detail == "already exists"


class TestTooManyRequests:
    def test_status_429(self):
        exc = TooManyRequests()
        assert exc.status_code == 429

    def test_retry_after_header(self):
        exc = TooManyRequests(retry_after=60)
        assert exc.headers.get("Retry-After") == "60"

    def test_no_retry_after_header(self):
        exc = TooManyRequests()
        assert "Retry-After" not in exc.headers


class TestServiceUnavailable:
    def test_status_503(self):
        exc = ServiceUnavailable()
        assert exc.status_code == 503

    def test_custom_detail(self):
        exc = ServiceUnavailable("maintenance")
        assert exc.detail == "maintenance"


class TestORMExceptions:
    def test_does_not_exist(self):
        exc = DoesNotExist("no match")
        assert isinstance(exc, ORMException)

    def test_multiple_objects_returned(self):
        exc = MultipleObjectsReturned("too many")
        assert isinstance(exc, ORMException)

    def test_integrity_error(self):
        exc = IntegrityError("constraint violated")
        assert isinstance(exc, ORMException)


class TestMigrationError:
    def test_is_openviper_exception(self):
        exc = MigrationError("migration failed")
        assert isinstance(exc, OpenViperException)


class TestAuthenticationFailed:
    def test_status_401(self):
        exc = AuthenticationFailed()
        assert exc.status_code == 401

    def test_default_detail(self):
        exc = AuthenticationFailed()
        assert "Invalid credentials" in exc.detail

    def test_custom_detail(self):
        exc = AuthenticationFailed("wrong password")
        assert exc.detail == "wrong password"


class TestTokenExpired:
    def test_status_401(self):
        exc = TokenExpired()
        assert exc.status_code == 401

    def test_detail_contains_expired(self):
        exc = TokenExpired()
        assert "expired" in exc.detail.lower()


class TestMiddlewareException:
    def test_is_openviper_exception(self):
        exc = MiddlewareException("middleware error")
        assert isinstance(exc, OpenViperException)
