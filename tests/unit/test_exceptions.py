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


def test_settings_validation_error():
    exc = SettingsValidationError(["error1", "error2"])
    assert "error1" in str(exc)
    assert "error2" in str(exc)
    assert exc.errors == ["error1", "error2"]


def test_http_exception_defaults():
    exc = HTTPException(400)
    assert exc.status_code == 400
    assert exc.detail == "Bad Request"
    assert exc.headers == {}


def test_http_exception_custom():
    exc = HTTPException(418, detail="I'm a teapot", headers={"X-Teapot": "true"})
    assert exc.status_code == 418
    assert exc.detail == "I'm a teapot"
    assert exc.headers == {"X-Teapot": "true"}


def test_http_exception_unknown_status():
    exc = HTTPException(999)
    assert exc.detail == "Error"


def test_not_found():
    exc = NotFound("Custom not found")
    assert exc.status_code == 404
    assert exc.detail == "Custom not found"


def test_method_not_allowed():
    exc = MethodNotAllowed(["GET", "POST"])
    assert exc.status_code == 405
    assert exc.headers["Allow"] == "GET, POST"


def test_unauthorized():
    exc = Unauthorized()
    assert exc.status_code == 401
    assert "WWW-Authenticate" in exc.headers


def test_validation_error():
    exc = ValidationError({"field": "error"})
    assert exc.status_code == 422
    assert exc.validation_errors == {"field": "error"}


def test_too_many_requests():
    exc = TooManyRequests(retry_after=60)
    assert exc.status_code == 429
    assert exc.headers["Retry-After"] == "60"


def test_token_expired():
    exc = TokenExpired()
    assert exc.status_code == 401
    assert "expired" in exc.detail.lower()


def test_ai_model_not_found():
    exc = ModelNotFoundError("gpt-5", available=["gpt-4"])
    assert "gpt-5" in str(exc)
    assert "gpt-4" in str(exc)
    assert exc.model == "gpt-5"
    assert exc.available == ["gpt-4"]


def test_ai_model_collision():
    exc = ModelCollisionError("m1", "p1", "p2")
    assert "m1" in str(exc)
    assert "p1" in str(exc)
    assert "p2" in str(exc)
    assert exc.model == "m1"
    assert exc.existing_provider == "p1"
    assert exc.new_provider == "p2"


def test_simple_exceptions():
    # Just instantiate to ensure no syntax/runtime errors in definitions
    assert isinstance(ImproperlyConfigured(), OpenViperException)
    assert isinstance(PermissionDenied(), HTTPException)
    assert isinstance(Conflict(), HTTPException)
    assert isinstance(ServiceUnavailable(), HTTPException)
    assert isinstance(AuthenticationFailed(), HTTPException)
    assert isinstance(ORMException(), OpenViperException)
    assert isinstance(DoesNotExist(), ORMException)
    assert isinstance(MultipleObjectsReturned(), ORMException)
    assert isinstance(IntegrityError(), ORMException)
    assert isinstance(MigrationError(), OpenViperException)
    assert isinstance(FieldError(), ORMException)
    assert isinstance(MiddlewareException(), OpenViperException)
    assert isinstance(AIException(), OpenViperException)
