from openviper.ai.exceptions import ModelNotFoundError
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


def test_settings_validation_error():
    err = SettingsValidationError(["missing secret", "bad DB"])
    assert err.errors == ["missing secret", "bad DB"]
    assert "missing secret" in str(err)
    assert "bad DB" in str(err)


def test_http_exception():
    e1 = HTTPException(400)
    assert e1.status_code == 400
    assert e1.detail == "Bad Request"
    assert e1.headers == {}
    assert "HTTP 400: Bad Request" in str(e1)

    e2 = HTTPException(999)  # Invalid HTTPStatus fallback
    assert e2.status_code == 999
    assert e2.detail == "Error"

    e3 = HTTPException(403, "Custom", {"X-Hdr": "1"})
    assert e3.detail == "Custom"
    assert e3.headers == {"X-Hdr": "1"}


def test_http_exception_subclasses():
    nf = NotFound()
    assert nf.status_code == 404
    assert nf.detail == "Not found."

    mna = MethodNotAllowed(["GET", "POST"])
    assert mna.status_code == 405
    assert mna.headers["Allow"] == "GET, POST"

    pd = PermissionDenied()
    assert pd.status_code == 403

    una = Unauthorized()
    assert una.status_code == 401
    assert una.headers["WWW-Authenticate"] == "Bearer"

    ve = ValidationError({"field": "bad"})
    assert ve.status_code == 422
    assert ve.validation_errors == {"field": "bad"}
    assert ve.detail == {"field": "bad"}

    con = Conflict()
    assert con.status_code == 409

    tmr1 = TooManyRequests()
    assert tmr1.status_code == 429
    assert "Retry-After" not in tmr1.headers

    tmr2 = TooManyRequests(retry_after=60)
    assert tmr2.headers["Retry-After"] == "60"

    su = ServiceUnavailable()
    assert su.status_code == 503


def test_auth_exceptions():
    af = AuthenticationFailed("bad pass")
    assert af.status_code == 401
    assert af.detail == "bad pass"
    assert af.headers["WWW-Authenticate"] == "Bearer"

    te = TokenExpired()
    assert te.status_code == 401
    assert te.detail == "Token has expired."


def test_base_exceptions_instantiation():
    # Just ensure they can be instantiated without errors
    _ = OpenViperException()
    _ = ImproperlyConfigured()
    _ = ORMException()
    _ = DoesNotExist()
    _ = MultipleObjectsReturned()
    _ = IntegrityError()
    _ = MigrationError()
    _ = MiddlewareException()


def test_model_not_found_error_with_available_list():

    err = ModelNotFoundError("gpt-4", available=["gpt-3.5", "claude-3"])
    assert "gpt-4" in str(err)
    assert "Available models" in str(err)
    assert err.model == "gpt-4"
    assert err.available == ["gpt-3.5", "claude-3"]


def test_model_not_found_error_without_available_list():
    """ModelNotFoundError without available list has empty .available."""

    err = ModelNotFoundError("unknown-model")
    assert "unknown-model" in str(err)
    assert "Available" not in str(err)
    assert err.available == []
