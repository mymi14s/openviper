"""OpenViper settings & configuration system.

Frozen dataclass loaded from ``OPENVIPER_SETTINGS_MODULE`` with
environment-variable and ``.env`` overrides.  Environment detection
uses ``OPENVIPER_ENV`` (default: ``development``).

Priority (highest first): env vars → settings module → field defaults.
"""

from __future__ import annotations

import dataclasses
import importlib
import io
import json
import logging
import logging.config
import os
import secrets
import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from dotenv import find_dotenv, load_dotenv

from openviper.conf.task_defaults import DEFAULT_TASKS
from openviper.exceptions import ImproperlyConfigured, SettingsValidationError
from openviper.version import __version__ as framework_version

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

    from openviper.conf.types import ConfigMap, ConfigValue, EnvValue

logger = logging.getLogger("openviper.conf")

DOTENV_LOADED: bool = False

if not DOTENV_LOADED:
    dotenv_path = find_dotenv(usecwd=True) or ".env"
    load_dotenv(dotenv_path=dotenv_path, override=False)
    DOTENV_LOADED = True

MODULE_CACHE: dict[str, types.ModuleType] = {}

SETTINGS_CLASS_CACHE: dict[str, type[Settings]] = {}

# Keyed by Settings class to support subclasses correctly
FIELD_METADATA_CACHE: dict[type, list[tuple[str, type]]] = {}

LOG_DATETIME_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
"""Datetime format string used by both JSON and text log formatters."""

SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "SECRET_KEY",
        "DATABASES",
        "CACHES",
        "EMAIL",
    },
)

INSECURE_JWT_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {
        "none",
        "None",
        "NONE",
    },
)


def cast_bool(v: str) -> bool:
    """Return ``True`` when *v* is a truthy string value."""
    return v.lower() in ("1", "true", "yes", "on")


def cast_tuple(v: str) -> tuple[str, ...]:
    """Split a comma-separated string into a tuple of stripped values."""
    return tuple(x.strip() for x in v.split(",") if x.strip())


def cast_timedelta(v: str) -> timedelta:
    """Convert a numeric string to a :class:`~datetime.timedelta` in seconds."""
    return timedelta(seconds=int(v))


MIN_SECRET_KEY_LENGTH: Final[int] = 50
MIN_HSTS_SECONDS: Final[int] = 31536000

INSECURE_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {"INSECURE-CHANGE-ME", "dev-insecure-key", ""},
)


def is_insecure_secret_key(key: str) -> bool:
    """Return ``True`` when *key* is empty or a known insecure value."""
    return not key or key in INSECURE_SECRET_KEYS


ENV_CASTERS: Final[dict[type, Callable[[str], EnvValue]]] = {
    bool: cast_bool,
    int: int,
    float: float,
    str: str,
    tuple: cast_tuple,
    timedelta: cast_timedelta,
}


def cast_env_value(current: EnvValue, raw: str) -> EnvValue | None:
    """Cast *raw* env-var string to the same type as *current*."""
    caster = ENV_CASTERS.get(type(current))
    if caster is None:
        return None  # dicts and other complex types: skip env-var override
    try:
        return caster(raw)
    except (ValueError, TypeError) as exc:
        logger.debug("Could not cast env var value %r: %s", raw, exc)
        return None


@dataclasses.dataclass(slots=True, frozen=True)
class Settings:
    """Base configuration dataclass for OpenViper.

    All fields are immutable after construction.  Sequence defaults use
    ``tuple`` rather than ``list`` to enforce immutability.
    """

    PROJECT_NAME: str = "OpenViper Application"
    VERSION: str = framework_version
    DEBUG: bool = True
    ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")
    INSTALLED_APPS: tuple[str, ...] = ()
    USE_TZ: bool = True
    TIME_ZONE: str = "UTC"
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
    )

    ADMIN_SETTINGS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "title": "OpenViper Admin",
            "header_title": "OpenViper",
            "footer_title": "OpenViper Admin",
        },
    )

    # WARNING: Generate a secure SECRET_KEY using generate_secret_key()
    # NEVER use this default in production! Set via environment or config.
    SECRET_KEY: str = ""

    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
                "OPTIONS": {
                    "URL": "",
                    "ECHO": False,
                    "POOL_SIZE": 5,
                    "MAX_OVERFLOW": 10,
                    "POOL_RECYCLE": 3600,
                },
            },
            "ROUTERS": [],
            "ROUTING": {},
        },
    )

    CACHES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "BACKEND": "openviper.cache.InMemoryCache",
                "OPTIONS": {
                    "ttl": 300,
                },
            },
        },
    )

    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")
    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=1))

    # IMPORTANT: SESSION_COOKIE_SECURE should be True in
    # production (requires HTTPS).
    # Set to False only for local development without HTTPS
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True  # Always True for XSS protection
    SESSION_COOKIE_SAMESITE: str = (
        "Lax"  # Lax=good default, Strict=max security, None=requires Secure
    )
    SESSION_COOKIE_PATH: str = "/"
    SESSION_COOKIE_DOMAIN: str | None = None

    USER_MODEL: str = "openviper.auth.models.User"
    AUTH_SESSION_ENABLED: bool = True
    SESSION_STORE: str = "database"  # "database" | custom dotted path
    AUTH_BACKENDS: tuple[str, ...] = dataclasses.field(
        default_factory=lambda: (
            "openviper.auth.backends.jwt_backend.JWTBackend",
            "openviper.auth.backends.session_backend.SessionBackend",
        ),
    )

    DEFAULT_AUTHENTICATION_CLASSES: tuple[str, ...] = (
        "openviper.auth.authentications.JWTAuthentication",
        "openviper.auth.authentications.SessionAuthentication",
    )
    DEFAULT_PERMISSION_CLASSES: tuple[str, ...] = ()

    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE: timedelta = dataclasses.field(
        default_factory=lambda: timedelta(minutes=30),
    )
    JWT_REFRESH_TOKEN_EXPIRE: timedelta = dataclasses.field(
        default_factory=lambda: timedelta(days=7),
    )

    CSRF_COOKIE_NAME: str = "csrftoken"
    CSRF_COOKIE_SECURE: bool = False
    CSRF_COOKIE_HTTPONLY: bool = (
        False  # Must be False for double-submit cookie pattern (JS reads the token)
    )
    CSRF_COOKIE_SAMESITE: str = "Lax"
    CSRF_TRUSTED_ORIGINS: tuple[str, ...] = ()

    CORS_ALLOWED_ORIGINS: tuple[str, ...] = ()
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_ALLOWED_METHODS: tuple[str, ...] = (
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    )
    CORS_ALLOWED_HEADERS: tuple[str, ...] = ("*",)
    CORS_EXPOSE_HEADERS: tuple[str, ...] = ()
    CORS_MAX_AGE: int = 600

    STATIC_URL: str = "/static/"
    STATIC_ROOT: str = "./static/"
    STATICFILES_DIRS: tuple[str, ...] = ("static/",)
    MEDIA_URL: str = "/media/"
    MEDIA_ROOT: str = "./media/"
    MEDIA_DIR: str = "./media/"

    TEMPLATES_DIR: str = "templates/"
    TEMPLATE_AUTO_RELOAD: bool = True
    JINJA_PLUGINS: ConfigMap = dataclasses.field(default_factory=dict)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "text" | "json"
    LOGGING: ConfigMap = dataclasses.field(default_factory=dict)
    EMAIL: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "backend": "SMTPBackend",  # "ConsoleBackend" | "SMTPBackend"
            "host": "localhost",
            "port": 587,
            "use_tls": True,
            "use_ssl": False,
            "timeout": 10,
            "username": "",
            "user": "",
            "password": "",
            "from": "",
            "default_sender": "noreply@example.com",
            "fail_silently": False,
            "background": False,
        },
    )

    SECURE_SSL_REDIRECT: bool = False
    SECURE_HSTS_SECONDS: int = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = False
    SECURE_HSTS_PRELOAD: bool = False
    SECURE_COOKIES: bool = False
    X_FRAME_OPTIONS: str = "DENY"
    # X-XSS-Protection is deprecated; modern browsers ignore it and IE's
    # implementation introduced XSS vectors. Use CSP instead.
    SECURE_BROWSER_XSS_FILTER: bool = False
    SECURE_CONTENT_SECURITY_POLICY: ConfigMap | None = None

    RATE_LIMIT_BACKEND: str = "memory"  # "memory" | "redis"
    RATE_LIMIT_REQUESTS: int = 10000
    RATE_LIMIT_WINDOW: int = 60
    RATE_LIMIT_BY: str = "ip"  # "ip" | "user" | "path"

    MODEL_EVENTS: ConfigMap = dataclasses.field(default_factory=dict)

    TASKS: ConfigMap = dataclasses.field(
        default_factory=lambda: {**DEFAULT_TASKS},
    )

    OAUTH2_EVENTS: dict[str, str] = dataclasses.field(default_factory=dict)

    ENABLE_AI_PROVIDERS: bool = False
    AI_PROVIDERS: ConfigMap = dataclasses.field(default_factory=dict)

    OPENAPI: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "title": "OpenViper API",
            "version": "0.0.1",
            "description": "",
            "docs_url": "/open-api/docs",
            "redoc_url": "/open-api/redoc",
            "schema_url": "/open-api/openapi.json",
            "enabled": True,
            "admin_url": None,
            "exclude": [],
        },
    )

    MAX_FILE_SIZE: int = 10 * 1024 * 1024

    STATIC_STORAGE: str = "local"  # "local" | "s3"
    MEDIA_STORAGE: str = "local"

    COUNTRY_FIELD: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "EXTRA_COUNTRIES": {},
            "ENABLE_CACHE": True,
            "STRICT": True,
        },
    )

    def as_dict(self, *, mask_sensitive: bool = True) -> ConfigMap:
        """Return all settings as a plain dict (shallow copy).

        Sensitive fields (SECRET_KEY, DATABASES, CACHES, etc.)
        are masked by default to prevent accidental leakage into logs or
        API responses.  Pass ``mask_sensitive=False`` to get raw values.
        """
        result: ConfigMap = {}
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            if mask_sensitive and f.name in SENSITIVE_FIELDS and val:
                result[f.name] = "***"
            else:
                result[f.name] = val
        return result

    def __getitem__(self, item: str) -> ConfigValue:
        """Allow dict-style access to settings fields."""
        return cast("ConfigValue", getattr(self, item))


def load_settings_from_module(module_path: str) -> Settings | None:
    """Import *module_path* and return a :class:`Settings` instance from it.

    Returns ``None`` when *module_path* is empty or when the special
    ``"settings"`` module cannot be found (graceful fallback).
    """
    if not module_path:
        return None

    if module_path in SETTINGS_CLASS_CACHE:
        settings_class = SETTINGS_CLASS_CACHE[module_path]
        logger.debug(
            "Loaded cached settings class %r from %r",
            settings_class.__name__,
            module_path,
        )
        return settings_class()

    try:
        if module_path in MODULE_CACHE:
            mod = MODULE_CACHE[module_path]
        else:
            mod = importlib.import_module(module_path)
            MODULE_CACHE[module_path] = mod

        # Modules often import a base settings class
        # and then define a more specific subclass; we want the
        # deepest one (highest MRO depth).
        candidates: list[tuple[str, type[Settings]]] = []
        for attr_name, obj in vars(mod).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, Settings)
                and obj is not Settings
                and dataclasses.is_dataclass(obj)
            ):
                candidates.append((attr_name, obj))

        if candidates:
            attr_name, best = max(candidates, key=lambda c: len(c[1].__mro__))
            SETTINGS_CLASS_CACHE[module_path] = best
            logger.debug(
                "Loaded settings class %r from %r",
                attr_name,
                module_path,
            )
            return best()

        msg = (
            f"OPENVIPER_SETTINGS_MODULE={module_path!r} was imported "
            "but contains no Settings subclass. Define a frozen dataclass "
            "that subclasses openviper.conf.settings.Settings."
        )
        raise RuntimeError(msg)
    except ImportError as exc:
        if module_path == "settings":
            logger.debug(
                "OPENVIPER_SETTINGS_MODULE='settings' is not importable; "
                "falling back to default settings.",
            )
            return None
        msg = f"Could not import OPENVIPER_SETTINGS_MODULE={module_path!r}: {exc}"
        raise RuntimeError(msg) from exc


class LazySettings:
    """Thread-safe proxy to the active :class:`Settings` instance.

    Loaded lazily on first attribute access.  Use :meth:`configure` for
    programmatic setup before any access occurs.

    Attribute writes for non-underscore names are forbidden after the
    settings are configured; this prevents accidental mutation at runtime.
    """

    instance: Settings | None
    configured: bool
    lock: threading.RLock

    def __init__(self) -> None:
        """Initialise an unconfigured lazy settings proxy."""
        self.instance = None
        self.configured = False
        self.lock = threading.RLock()

    def configure(self, settings_obj: Settings) -> None:
        """Set the active settings instance.

        Raises:
            RuntimeError: If called after settings are already configured.

        """
        with self.lock:
            if self.configured:
                msg = (
                    "settings.configure() called more than once.  "
                    "It must be called exactly once, before any settings are accessed."
                )
                raise RuntimeError(
                    msg,
                )
            self.instance = settings_obj
            self.configured = True
            logger.debug("Settings configured programmatically: %r", type(settings_obj).__name__)

    def setup(self, *, force: bool = False) -> None:
        """Load settings from ``OPENVIPER_SETTINGS_MODULE``.

        Protected by ``lock``; uses double-checked locking so the fast path
        (already configured) has zero lock overhead.

        Args:
            force: When ``True``, re-run setup even if settings are already
                configured.  Useful for ``viperctl.py`` which sets
                ``OPENVIPER_SETTINGS_MODULE`` *after* framework modules are
                imported.

        """
        if self.configured and not force:
            return
        with self.lock:
            if self.configured and not force:
                return

            module_path = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
            settings_instance = load_settings_from_module(module_path)

            if settings_instance is None:
                settings_instance = Settings()

            if module_path:
                settings_instance = auto_include_project_app(settings_instance, module_path)

            settings_instance = apply_env_overrides(settings_instance)

            env = os.environ.get("OPENVIPER_ENV", "development")
            if env != "production" and is_insecure_secret_key(settings_instance.SECRET_KEY):
                object.__setattr__(settings_instance, "SECRET_KEY", generate_secret_key())

            validate_settings(settings_instance, env)

            self.instance = settings_instance
            self.configured = True

            configure_logging(settings_instance)

    def __getattr__(self, name: str) -> ConfigValue:
        """Delegate attribute reads to the underlying :class:`Settings`."""
        if not self.configured:
            self.setup()
        inst = self.instance
        if inst is None:
            msg = (
                "Settings have not been configured.  Set OPENVIPER_SETTINGS_MODULE "
                "or call settings.configure() before importing from openviper."
            )
            raise ImproperlyConfigured(
                msg,
            )
        return cast("ConfigValue", getattr(inst, name))

    def __setattr__(self, name: str, value: object) -> None:
        """Prevent runtime mutation of configured settings."""
        if name.startswith("_") or name in ("instance", "configured", "lock"):
            object.__setattr__(self, name, value)
            return
        msg = (
            f"Settings are read-only.  Cannot set {name!r} directly.  "
            "Pass a new Settings instance to settings.configure() instead."
        )
        raise AttributeError(
            msg,
        )

    def __repr__(self) -> str:
        """Return a human-readable representation of the proxy state."""
        if self.configured and self.instance is not None:
            return (
                f"<LazySettings [{type(self.instance).__name__}] "
                f"PROJECT_NAME={self.instance.PROJECT_NAME!r} "
                f"DEBUG={self.instance.DEBUG!r}>"
            )
        return "<LazySettings [not configured]>"


def auto_include_project_app(instance: Settings, module_path: str) -> Settings:
    """Prepend the top-level project package to ``INSTALLED_APPS`` if absent."""
    project_app = module_path.split(".", maxsplit=1)[0]
    if not project_app:
        return instance
    if project_app in instance.INSTALLED_APPS:
        return instance
    return dataclasses.replace(
        instance,
        INSTALLED_APPS=(project_app, *instance.INSTALLED_APPS),
    )


def apply_env_overrides(instance: Settings) -> Settings:
    """Return a new :class:`Settings` with env-var overrides applied.

    Field metadata is cached per Settings subclass to avoid recomputing
    dataclasses.fields() on every request.
    """
    cls = type(instance)

    if cls not in FIELD_METADATA_CACHE:
        cache: list[tuple[str, type]] = []
        for f in dataclasses.fields(instance):
            if f.name.isupper():
                current_value = getattr(instance, f.name)
                field_type = type(current_value)
                cache.append((f.name, field_type))
        FIELD_METADATA_CACHE[cls] = cache

    overrides: dict[str, EnvValue] = {}
    for field_name, _field_type in FIELD_METADATA_CACHE[cls]:
        raw = os.environ.get(field_name)
        if raw is None:
            continue
        current = getattr(instance, field_name)
        casted = cast_env_value(current, raw)
        if casted is not None:
            overrides[field_name] = casted

    if not overrides:
        return instance
    current_values = dataclasses.asdict(instance)
    current_values.update(overrides)
    return type(instance)(**current_values)


settings = LazySettings()


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter - no third-party dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string."""
        payload: dict[str, str | list[str]] = {
            "time": self.formatTime(record, LOG_DATETIME_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload)


class OVDefaultHandler(logging.StreamHandler[io.TextIOWrapper]):
    """Sentinel StreamHandler installed by :func:`configure_logging`.

    Using a distinct subclass lets :func:`configure_logging` remove its own
    handler on a subsequent call without touching handlers added by the
    application or third-party libraries.
    """


def configure_logging(instance: Settings) -> None:
    """Apply logging configuration derived from *instance*.

    ``LOGGING`` is passed verbatim to ``logging.config.dictConfig``
    when non-empty.  Otherwise a console handler is installed on the
    ``openviper`` logger using ``LOG_LEVEL`` and ``LOG_FORMAT``.
    """
    if instance.LOGGING:
        logging.config.dictConfig(instance.LOGGING)
        return

    level = getattr(logging, instance.LOG_LEVEL.upper(), logging.INFO)

    if instance.LOG_FORMAT == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
            datefmt=LOG_DATETIME_FORMAT,
        )

    handler = OVDefaultHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)

    ov_logger = logging.getLogger("openviper")
    ov_logger.setLevel(level)
    ov_logger.handlers = [h for h in ov_logger.handlers if not isinstance(h, OVDefaultHandler)]
    ov_logger.addHandler(handler)

    if level > logging.DEBUG:
        for noisy in (
            "aiosqlite",
            "asyncio",
            "urllib3",
            "urllib3.connectionpool",
            "watchfiles",
            "watchfiles.main",
            "sqlalchemy.engine",
            "sqlalchemy.pool",
            "dramatiq",
        ):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def validate_production(s: Settings, errors: list[str]) -> None:
    """Append production-specific validation errors to *errors*."""
    if s.DEBUG:
        errors.append("DEBUG must be False in production.")
    if is_insecure_secret_key(s.SECRET_KEY):
        errors.append("SECRET_KEY must be set to a strong random value in production.")
    elif len(s.SECRET_KEY) < MIN_SECRET_KEY_LENGTH:
        errors.append("SECRET_KEY must be at least 50 characters long in production.")
    validate_production_security(s, errors)
    validate_production_cookies(s, errors)
    validate_production_api(s, errors)


def validate_production_security(s: Settings, errors: list[str]) -> None:
    """Append production security-header validation errors to *errors*."""
    if not s.SECURE_COOKIES:
        errors.append("SECURE_COOKIES must be True in production.")
    if not s.ALLOWED_HOSTS:
        errors.append("ALLOWED_HOSTS must contain at least one entry in production.")
    if not s.SECURE_SSL_REDIRECT:
        errors.append("SECURE_SSL_REDIRECT must be True in production.")
    if s.SECURE_HSTS_SECONDS < MIN_HSTS_SECONDS:
        errors.append("SECURE_HSTS_SECONDS must be at least 31536000 (1 year) in production.")


def validate_production_cookies(s: Settings, errors: list[str]) -> None:
    """Append production cookie validation errors to *errors*."""
    if not s.SESSION_COOKIE_SECURE:
        errors.append("SESSION_COOKIE_SECURE must be True in production.")
    if not s.CSRF_COOKIE_SECURE:
        errors.append("CSRF_COOKIE_SECURE must be True in production.")


def validate_production_api(s: Settings, errors: list[str]) -> None:
    """Append production API exposure validation errors to *errors*."""
    if s.OPENAPI.get("enabled", True):
        errors.append(
            "OPENAPI['enabled'] should be False in production to avoid exposing API docs.",
        )
    if s.CORS_ALLOWED_HEADERS == ("*",):
        errors.append("CORS_ALLOWED_HEADERS should not be wildcard ('*') in production.")


def validate_settings(s: Settings, env: str) -> None:
    """Validate *s* for the given deployment environment.

    Raises:
        SettingsValidationError: If any validation check fails.

    """
    errors: list[str] = []

    if s.JWT_ALGORITHM in INSECURE_JWT_ALGORITHMS:
        errors.append(
            f"JWT_ALGORITHM={s.JWT_ALGORITHM!r} is insecure. "
            "Use HS256, HS384, HS512, RS256, RS384, RS512, ES256, ES384, or ES512.",
        )

    if env == "production":
        validate_production(s, errors)
    elif is_insecure_secret_key(s.SECRET_KEY):
        logger.warning(
            "SECRET_KEY not set. Auto-generating a random key for development. "
            "Set SECRET_KEY in environment for production!",
        )

    databases = s.DATABASES
    if not databases or not isinstance(databases, dict):
        errors.append("DATABASES must be a non-empty dict with at least a 'default' alias.")
    elif "default" not in databases:
        errors.append("DATABASES must contain a 'default' alias.")

    if s.SESSION_COOKIE_SAMESITE.lower() == "none" and not s.SESSION_COOKIE_SECURE:
        errors.append("SESSION_COOKIE_SECURE must be True when SESSION_COOKIE_SAMESITE is 'None'.")

    if errors:
        raise SettingsValidationError(errors)


def generate_secret_key(length: int = 64) -> str:
    """Generate a cryptographically secure secret key."""
    return secrets.token_urlsafe(length)
