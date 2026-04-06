"""OpenViper settings & configuration system.

Settings are defined as a frozen dataclass, loaded from
``OPENVIPER_SETTINGS_MODULE`` and overridable via environment variables
or ``.env`` files through python-dotenv.

Environment detection uses ``OPENVIPER_ENV`` (default: ``development``).

Configuration sources (highest to lowest priority):
  1. Environment variables matching uppercase field names.
  2. Settings class resolved from ``OPENVIPER_SETTINGS_MODULE``.
  3. Default field values on :class:`Settings`.

``configure()`` must be called before any attribute is first accessed
when using programmatic setup.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import logging
import logging.config
import os
import secrets
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final

from openviper._version import __version__ as _framework_version
from openviper.exceptions import ImproperlyConfigured, SettingsValidationError

logger = logging.getLogger("openviper.conf")

try:
    from dotenv import load_dotenv as _load_dotenv

    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

# Track if .env has been loaded to avoid redundant I/O
_DOTENV_LOADED: bool = False

# Cache imported settings modules by path to avoid repeated imports
_MODULE_CACHE: dict[str, Any] = {}

# Cache Settings class instances by module path for faster lookups
_SETTINGS_CLASS_CACHE: dict[str, type[Settings]] = {}

# Cache field metadata for faster environment variable casting
# Keyed by Settings class to support subclasses correctly
_FIELD_METADATA_CACHE: dict[type, list[tuple[str, type]]] = {}

# Fields that must never appear in as_dict() or repr output
_SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "SECRET_KEY",
        "DATABASE_URL",
        "EMAIL",
    }
)

# JWT algorithms that are considered insecure
_INSECURE_JWT_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {
        "none",
        "None",
        "NONE",
    }
)


def _cast_bool(v: str) -> bool:
    return v.lower() in ("1", "true", "yes", "on")


def _cast_tuple(v: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in v.split(",") if x.strip())


def _cast_timedelta(v: str) -> timedelta:
    return timedelta(seconds=int(v))


_ENV_CASTERS: Final[dict[type, Callable[[str], Any]]] = {
    bool: _cast_bool,
    int: int,
    float: float,
    str: str,
    tuple: _cast_tuple,
    timedelta: _cast_timedelta,
}


def _cast_env_value(current: Any, raw: str) -> Any:
    """Cast *raw* env-var string to the same type as *current*."""
    caster = _ENV_CASTERS.get(type(current))
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

    # ── Project ───────────────────────────────────────────────────────────
    PROJECT_NAME: str = "OpenViper Application"
    VERSION: str = _framework_version
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

    # ── Admin Panel ───────────────────────────────────────────────────────
    ADMIN_TITLE: str = "OpenViper Admin"
    ADMIN_HEADER_TITLE: str = "OpenViper"
    ADMIN_FOOTER_TITLE: str = "OpenViper Admin"

    # ── Secret Key ────────────────────────────────────────────────────────
    # WARNING: Generate a secure SECRET_KEY using generate_secret_key()
    # NEVER use this default in production! Set via environment variable.
    SECRET_KEY: str = ""  # Must be set via environment or config

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = ""
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE: int = 3600

    # ── Cache ─────────────────────────────────────────────────────────────
    CACHE_BACKEND: str = "memory"  # "memory" | "redis"
    CACHE_URL: str = ""
    CACHE_TTL: int = 300
    CACHES: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── Authentication & Session ──────────────────────────────────────────
    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")
    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=1))

    # Cookie security settings
    # IMPORTANT: SESSION_COOKIE_SECURE should be True in production (requires HTTPS)
    # Set to False only for local development without HTTPS
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True  # Always True for XSS protection
    SESSION_COOKIE_SAMESITE: str = (
        "Lax"  # Lax=good default, Strict=max security, None=requires Secure
    )
    SESSION_COOKIE_PATH: str = "/"  # Cookie available on all paths
    SESSION_COOKIE_DOMAIN: str | None = None  # None = let browser determine domain

    USER_MODEL: str = "openviper.auth.models.User"
    AUTH_SESSION_ENABLED: bool = True
    SESSION_STORE: str = "database"  # "database" | custom dotted path
    AUTH_BACKENDS: tuple[str, ...] = dataclasses.field(
        default_factory=lambda: (
            "openviper.auth.backends.jwt_backend.JWTBackend",
            "openviper.auth.backends.session_backend.SessionBackend",
        )
    )

    DEFAULT_AUTHENTICATION_CLASSES: tuple[str, ...] = (
        "openviper.auth.authentications.JWTAuthentication",
        "openviper.auth.authentications.SessionAuthentication",
    )
    DEFAULT_PERMISSION_CLASSES: tuple[str, ...] = ("openviper.http.permissions.IsAuthenticated",)

    # ── JWT ───────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE: timedelta = dataclasses.field(
        default_factory=lambda: timedelta(minutes=30)
    )
    JWT_REFRESH_TOKEN_EXPIRE: timedelta = dataclasses.field(
        default_factory=lambda: timedelta(days=7)
    )

    # ── CSRF ──────────────────────────────────────────────────────────────
    CSRF_COOKIE_NAME: str = "csrftoken"
    CSRF_COOKIE_SECURE: bool = False
    CSRF_COOKIE_HTTPONLY: bool = (
        False  # Must be False for double-submit cookie pattern (JS reads the token)
    )
    CSRF_COOKIE_SAMESITE: str = "Lax"
    CSRF_TRUSTED_ORIGINS: tuple[str, ...] = ()

    # ── CORS ──────────────────────────────────────────────────────────────
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

    # ── Static Files ──────────────────────────────────────────────────────
    STATIC_URL: str = "/static/"
    STATIC_ROOT: str = "./static/"
    STATICFILES_DIRS: tuple[str, ...] = ("static/",)
    MEDIA_URL: str = "/media/"
    MEDIA_ROOT: str = "./media/"
    MEDIA_DIR: str = "./media/"

    # ── Templates ─────────────────────────────────────────────────────────
    TEMPLATES_DIR: str = "templates/"
    TEMPLATE_AUTO_RELOAD: bool = True
    # Jinja2 plugin loader configuration.
    # Set ``"enable": 1`` (or ``True``) and optionally ``"path"`` to activate
    # automatic filter / global discovery from a ``jinja_plugins/`` directory.
    #
    # Example::
    #
    #     JINJA_PLUGINS = {"enable": 1, "path": "jinja_plugins"}
    #
    # Subdirectory layout:
    #   jinja_plugins/filters/*.py  → registered as Jinja2 filters
    #   jinja_plugins/globals/*.py  → registered as Jinja2 globals
    JINJA_PLUGINS: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "text" | "json"
    # When non-empty this takes priority over LOG_LEVEL and LOG_FORMAT.
    LOGGING: dict[str, Any] = dataclasses.field(default_factory=dict)
    # ── Email ─────────────────────────────────────────────────────────────
    EMAIL: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "backend": "SMTPBackend",  # "ConsoleBackend" | "SMTPBackend"
            "host": "localhost",
            "port": 587,
            "use_tls": True,
            "use_ssl": False,
            "timeout": 10,
            "username": "",
            "user": "",
            "password": "",  # nosec B105
            "from": "",
            "default_sender": "noreply@example.com",
            "fail_silently": False,
            "use_background_worker": False,
        }
    )

    # ── Security Headers ─────────────────────────────────────────────────
    SECURE_SSL_REDIRECT: bool = False
    SECURE_HSTS_SECONDS: int = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = False
    SECURE_HSTS_PRELOAD: bool = False
    SECURE_COOKIES: bool = False
    X_FRAME_OPTIONS: str = "DENY"
    SECURE_BROWSER_XSS_FILTER: bool = True
    SECURE_CONTENT_SECURITY_POLICY: dict[str, Any] | None = None

    # ── Rate Limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_BACKEND: str = "memory"  # "memory" | "redis"
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60
    RATE_LIMIT_BY: str = "ip"  # "ip" | "user" | "path"

    # ── Background Tasks ─────────────────────────────────────────────────
    TASKS: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── Model Events ─────────────────────────────────────────────────────
    # Per-model lifecycle event hooks.  Only active when TASKS['enabled'] is
    # truthy.  Keys are ``"module.ClassName"`` paths; values are dicts of
    # ``{event_name: [dotted_callable_path, ...]}``.
    #
    # Supported event names (all nine Model lifecycle hooks):
    #   save/create:  before_validate, validate, before_insert, before_save,
    #                 after_insert, on_change
    #   save/update:  before_validate, validate, before_save, on_update, on_change
    #   delete:       on_delete, after_delete
    #
    # Example::
    #
    #     MODEL_EVENTS = {
    #         "blog.models.Post": {
    #             "before_validate": ["blog.events.sanitise_post"],
    #             "after_insert":    ["blog.events.create_likes"],
    #             "on_change":       ["blog.events.reindex_post"],
    #             "after_delete":    ["blog.events.cleanup_comments"],
    #         },
    #         "blog.models.Comment": {
    #             "after_insert": ["blog.events.notify_post_author"],
    #         },
    #     }
    MODEL_EVENTS: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── OAuth2 Events ─────────────────────────────────────────────────────
    # Lifecycle event hooks for the OAuth2 authentication flow.  Each key maps
    # to a dotted Python path of an async or sync callable that accepts a single
    # payload dict argument.
    #
    # Supported event names:
    #   on_success  — called after a successful OAuth2 login
    #   on_fail     — called when authentication fails (bad token, no account, …)
    #   on_error    — called when an unexpected exception occurs during the flow
    #   on_initial  — called the first time a user authenticates via OAuth2
    #
    # Example::
    #
    #     OAUTH2_EVENTS = {
    #         "on_success": "myapp.events.oauth_success",
    #         "on_fail":    "myapp.events.oauth_fail",
    #         "on_error":   "myapp.events.oauth_error",
    #         "on_initial": "myapp.events.oauth_initial",
    #     }
    OAUTH2_EVENTS: dict[str, str] = dataclasses.field(default_factory=dict)

    # ── AI Integration ───────────────────────────────────────────────────
    ENABLE_AI_PROVIDERS: bool = False
    AI_PROVIDERS: dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── OpenAPI / Swagger ─────────────────────────────────────────────────
    OPENAPI_TITLE: str = "OpenViper API"
    OPENAPI_VERSION: str = "0.0.1"
    OPENAPI_DOCS_URL: str = "/open-api/docs"
    OPENAPI_REDOC_URL: str = "/open-api/redoc"
    OPENAPI_SCHEMA_URL: str = "/open-api/openapi.json"
    OPENAPI_ENABLED: bool = True
    # Controls OpenAPI access and route exclusion.
    # "__ALL__" disables the OpenAPI router entirely.
    # A list of route prefixes (e.g. ["admin", "blogs"]) removes those
    # paths from the generated schema while keeping the docs endpoint active.
    OPENAPI_EXCLUDE: list[str] | str = dataclasses.field(default_factory=list)

    # ── File Uploads ──────────────────────────────────────────────────────
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

    # ── S3 / Storage ─────────────────────────────────────────────────────
    STATIC_STORAGE: str = "local"  # "local" | "s3"
    MEDIA_STORAGE: str = "local"

    # ── Country Field ─────────────────────────────────────────────────────
    # Configuration for openviper.contrib.countries.CountryField.
    # EXTRA_COUNTRIES: dict mapping custom alpha-2 codes to
    #     {"name": ..., "dial_code": ...} for project-specific regions.
    # ENABLE_CACHE: keep LRU caches warm (always True; exposed for tests).
    # STRICT: reject codes that are not exactly two ASCII letters.
    #
    # Example::
    #
    #     COUNTRY_FIELD = {
    #         "EXTRA_COUNTRIES": {"XA": {"name": "Atlantis", "dial_code": "+000"}},
    #         "ENABLE_CACHE": True,
    #         "STRICT": True,
    #     }
    COUNTRY_FIELD: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "EXTRA_COUNTRIES": {},
            "ENABLE_CACHE": True,
            "STRICT": True,
        }
    )

    def as_dict(self, *, mask_sensitive: bool = True) -> dict[str, Any]:
        """Return all settings as a plain dict (shallow copy).

        Sensitive fields (SECRET_KEY, DATABASE_URL, AWS credentials, etc.)
        are masked by default to prevent accidental leakage into logs or
        API responses.  Pass ``mask_sensitive=False`` to get raw values.
        """
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            if mask_sensitive and f.name in _SENSITIVE_FIELDS and val:
                result[f.name] = "***"
            else:
                result[f.name] = val
        return result

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class _LazySettings:
    """Thread-safe proxy to the active :class:`Settings` instance.

    Loaded lazily on first attribute access.  Use :meth:`configure` for
    programmatic setup before any access occurs.

    Attribute writes for non-underscore names are forbidden after the
    settings are configured; this prevents accidental mutation at runtime.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "_instance", None)
        object.__setattr__(self, "_configured", False)
        object.__setattr__(self, "_lock", threading.RLock())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def configure(self, settings_obj: Settings) -> None:
        """Programmatically set the active settings.

        Must be called **before** any attribute is first read.

        Raises:
            RuntimeError: If called after settings are already configured.
        """
        with self._lock:
            if self._configured:
                raise RuntimeError(
                    "settings.configure() called more than once.  "
                    "It must be called exactly once, before any settings are accessed."
                )
            object.__setattr__(self, "_instance", settings_obj)
            object.__setattr__(self, "_configured", True)
            logger.debug("Settings configured programmatically: %r", type(settings_obj).__name__)

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _setup(self, force: bool = False) -> None:
        """Load settings from ``OPENVIPER_SETTINGS_MODULE``.

        Protected by ``_lock``; uses double-checked locking so the fast path
        (already configured) has zero lock overhead.

        Args:
            force: When ``True``, re-run setup even if settings are already
                configured.  Useful for ``viperctl.py`` which sets
                ``OPENVIPER_SETTINGS_MODULE`` *after* framework modules are
                imported.
        """
        if self._configured and not force:
            return
        with self._lock:
            if self._configured and not force:  # double-check inside lock
                return

            # Load .env only once (avoid redundant I/O)
            global _DOTENV_LOADED
            if _HAS_DOTENV and not _DOTENV_LOADED:
                _load_dotenv(dotenv_path=".env", override=False)
                _DOTENV_LOADED = True

            module_path = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
            instance: Settings | None = None

            if module_path:
                # Cache the imported module to avoid repeated imports
                # Cache the Settings class once found
                if module_path in _SETTINGS_CLASS_CACHE:
                    settings_class = _SETTINGS_CLASS_CACHE[module_path]
                    instance = settings_class()
                    logger.debug(
                        "Loaded cached settings class %r from %r",
                        settings_class.__name__,
                        module_path,
                    )
                else:
                    try:
                        if module_path in _MODULE_CACHE:
                            mod = _MODULE_CACHE[module_path]
                        else:
                            mod = importlib.import_module(module_path)
                            _MODULE_CACHE[module_path] = mod

                        # Find a frozen dataclass subclass of Settings
                        for attr_name, obj in vars(mod).items():
                            if (
                                isinstance(obj, type)
                                and issubclass(obj, Settings)
                                and obj is not Settings
                                and dataclasses.is_dataclass(obj)
                            ):
                                # Cache the Settings class for future use
                                _SETTINGS_CLASS_CACHE[module_path] = obj
                                instance = obj()
                                logger.debug(
                                    "Loaded settings class %r from %r",
                                    attr_name,
                                    module_path,
                                )
                                break
                        if instance is None:
                            raise RuntimeError(
                                f"OPENVIPER_SETTINGS_MODULE={module_path!r} was imported "
                                "but contains no Settings subclass. Define a frozen dataclass "
                                "that subclasses openviper.conf.settings.Settings."
                            )
                    except ImportError as exc:
                        raise RuntimeError(
                            f"Could not import OPENVIPER_SETTINGS_MODULE={module_path!r}: {exc}"
                        ) from exc

            if instance is None:
                instance = Settings()

            # Auto-prepend project app derived from settings module path
            if module_path:
                instance = _auto_include_project_app(instance, module_path)

            # Apply env-var overrides (these take final priority)
            instance = _apply_env_overrides(instance)

            # Auto-generate SECRET_KEY for development/test if missing/empty
            env = os.environ.get("OPENVIPER_ENV", "development")
            if env != "production" and (
                not instance.SECRET_KEY or instance.SECRET_KEY in ("INSECURE-CHANGE-ME", "")
            ):
                object.__setattr__(instance, "SECRET_KEY", generate_secret_key())

            object.__setattr__(self, "_instance", instance)
            object.__setattr__(self, "_configured", True)

            configure_logging(instance)

    # ------------------------------------------------------------------
    # Attribute access
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if not self._configured:
            self._setup()
        instance = object.__getattribute__(self, "_instance")
        if instance is None:
            raise ImproperlyConfigured(
                "Settings have not been configured.  Set OPENVIPER_SETTINGS_MODULE "
                "or call settings.configure() before importing from openviper."
            )
        return getattr(instance, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        raise AttributeError(
            f"Settings are read-only.  Cannot set {name!r} directly.  "
            "Pass a new Settings instance to settings.configure() instead."
        )

    def __repr__(self) -> str:
        if self._configured and self._instance is not None:
            return (
                f"<_LazySettings [{type(self._instance).__name__}] "
                f"PROJECT_NAME={self._instance.PROJECT_NAME!r} "
                f"DEBUG={self._instance.DEBUG!r}>"
            )
        return "<_LazySettings [not configured]>"


def _auto_include_project_app(instance: Settings, module_path: str) -> Settings:
    """Prepend the top-level project package to ``INSTALLED_APPS`` if absent."""
    project_app = module_path.split(".")[0]
    if not project_app:
        return instance
    if project_app in instance.INSTALLED_APPS:
        return instance
    return dataclasses.replace(
        instance,
        INSTALLED_APPS=(project_app,) + instance.INSTALLED_APPS,
    )


def _apply_env_overrides(instance: Settings) -> Settings:
    """Return a new :class:`Settings` with env-var overrides applied.

    Field metadata is cached per Settings subclass to avoid recomputing
    dataclasses.fields() on every request.
    """
    cls = type(instance)

    # Build field metadata cache per Settings class to support subclasses
    if cls not in _FIELD_METADATA_CACHE:
        cache: list[tuple[str, type]] = []
        for f in dataclasses.fields(instance):
            if f.name.isupper():
                current_value = getattr(instance, f.name)
                field_type = type(current_value)
                cache.append((f.name, field_type))
        _FIELD_METADATA_CACHE[cls] = cache

    overrides: dict[str, Any] = {}
    for field_name, _field_type in _FIELD_METADATA_CACHE[cls]:
        raw = os.environ.get(field_name)
        if raw is None:
            continue
        current = getattr(instance, field_name)
        casted = _cast_env_value(current, raw)
        if casted is not None:
            overrides[field_name] = casted

    if not overrides:
        return instance
    return dataclasses.replace(instance, **overrides)


settings = _LazySettings()


class _JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter — no third-party dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload)


class _OVDefaultHandler(logging.StreamHandler):
    """Sentinel StreamHandler installed by :func:`configure_logging`.

    Using a distinct subclass lets :func:`configure_logging` remove its own
    handler on a subsequent call without touching handlers added by the
    application or third-party libraries.
    """


def configure_logging(instance: Settings) -> None:
    """Apply logging configuration derived from *instance*.

    If ``LOGGING`` is non-empty it is passed verbatim to
    ``logging.config.dictConfig`` and wins over all other settings.

    Otherwise a console handler is installed directly on the ``openviper``
    logger using ``LOG_LEVEL`` and ``LOG_FORMAT``.  ``propagate`` is left at
    its default (``True``) so that pytest's ``caplog`` fixture can capture
    ``openviper.*`` log records in tests, and so that external tools such as
    uvicorn can manage the root logger independently.
    """
    if instance.LOGGING:
        logging.config.dictConfig(instance.LOGGING)
        return

    level = getattr(logging, instance.LOG_LEVEL.upper(), logging.INFO)

    if instance.LOG_FORMAT == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = _OVDefaultHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)

    ov_logger = logging.getLogger("openviper")
    ov_logger.setLevel(level)
    # Replace any previously installed default handler; leave other handlers
    # (e.g. those added by tests or external frameworks) untouched.
    ov_logger.handlers = [h for h in ov_logger.handlers if not isinstance(h, _OVDefaultHandler)]
    ov_logger.addHandler(handler)


def validate_settings(s: Settings, env: str) -> None:
    """Validate *s* for the given deployment environment.

    Raises:
        SettingsValidationError: If any validation check fails.
    """
    errors: list[str] = []

    # Universal checks
    if s.JWT_ALGORITHM in _INSECURE_JWT_ALGORITHMS:
        errors.append(
            f"JWT_ALGORITHM={s.JWT_ALGORITHM!r} is insecure. "
            "Use HS256, HS384, HS512, RS256, RS384, RS512, ES256, ES384, or ES512."
        )

    if env == "production":
        if s.DEBUG:
            errors.append("DEBUG must be False in production.")
        if not s.SECRET_KEY or s.SECRET_KEY in (
            "INSECURE-CHANGE-ME",
            "dev-insecure-key",
            "",
        ):
            errors.append("SECRET_KEY must be set to a strong random value in production.")
        elif len(s.SECRET_KEY) < 50:
            errors.append("SECRET_KEY must be at least 50 characters long in production.")
        if not s.SECURE_COOKIES:
            errors.append("SECURE_COOKIES must be True in production.")
        if not s.ALLOWED_HOSTS:
            errors.append("ALLOWED_HOSTS must contain at least one entry in production.")
        if not s.SECURE_SSL_REDIRECT:
            errors.append("SECURE_SSL_REDIRECT must be True in production.")
        if s.SECURE_HSTS_SECONDS < 31536000:
            errors.append("SECURE_HSTS_SECONDS must be at least 31536000 (1 year) in production.")
        if not s.SESSION_COOKIE_SECURE:
            errors.append("SESSION_COOKIE_SECURE must be True in production.")
        if not s.CSRF_COOKIE_SECURE:
            errors.append("CSRF_COOKIE_SECURE must be True in production.")
        if s.OPENAPI_ENABLED:
            errors.append(
                "OPENAPI_ENABLED should be False in production to avoid exposing API docs."
            )
        if s.CORS_ALLOWED_HEADERS == ("*",):
            errors.append("CORS_ALLOWED_HEADERS should not be wildcard ('*') in production.")
    else:
        # Development/staging: Auto-generate SECRET_KEY if not set
        if not s.SECRET_KEY or s.SECRET_KEY in ("INSECURE-CHANGE-ME", ""):
            logger.warning(
                "SECRET_KEY not set. Auto-generating a random key for development. "
                "Set SECRET_KEY in environment for production!"
            )
            object.__setattr__(s, "SECRET_KEY", generate_secret_key())

    if not s.DATABASE_URL:
        errors.append("DATABASE_URL must be set.")

    if errors:
        raise SettingsValidationError(errors)


def generate_secret_key(length: int = 64) -> str:
    """Generate a cryptographically secure secret key."""
    return secrets.token_urlsafe(length)
