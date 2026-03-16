"""OpenViper settings & configuration system.

Settings are defined as a frozen dataclass, loaded from
``OPENVIPER_SETTINGS_MODULE`` and overridable via environment variables
or ``.env`` files through python-dotenv.

Environment detection uses ``OPENVIPER_ENV`` (default: ``development``).

Quick start
-----------
**Option A — module auto-discovery:**

.. code-block:: python

    # myproject/settings.py
    import dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        PROJECT_NAME: str = "MyBlog"
        DATABASE_URL: str = "sqlite:///db.sqlite3"

Then set ``OPENVIPER_SETTINGS_MODULE=myproject.settings`` in the environment.

**Option B — programmatic configuration:**

.. code-block:: python

    from openviper.conf import Settings
    from openviper.conf.settings import settings

    settings.configure(Settings(DATABASE_URL="sqlite:///db.sqlite3"))

``configure()`` must be called before any attribute is first accessed.
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import secrets
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final

from openviper.exceptions import ImproperlyConfigured, SettingsValidationError

logger = logging.getLogger("openviper.conf")

try:
    from dotenv import load_dotenv as _load_dotenv

    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

# ---------------------------------------------------------------------------
# caches (module-level)
# ---------------------------------------------------------------------------

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
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "EMAIL",
        "SENTRY_DSN",
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

# ---------------------------------------------------------------------------
# Typed cast table for env-var overrides
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Base Settings (frozen dataclass)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True, frozen=True)
class Settings:
    """Base configuration dataclass.  Subclass and ``@dataclass(frozen=True)``
    to customise for your project.

    All fields are immutable after construction.  ``list`` defaults from the
    old class-based system are represented as ``tuple`` here.
    """

    # ── Project ───────────────────────────────────────────────────────────
    PROJECT_NAME: str = "OpenViper Application"
    VERSION: str = "0.0.1"
    DEBUG: bool = True
    ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")
    ROOT_URLCONF: str = ""
    INSTALLED_APPS: tuple[str, ...] = ()
    USE_TZ: bool = True
    TIME_ZONE: str = "UTC"
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
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

    # ── Authentication & Session ──────────────────────────────────────────
    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")
    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=1))

    # Cookie security settings
    # IMPORTANT: SESSION_COOKIE_SECURE should be True in production (requires HTTPS)
    # Set to False only for local development without HTTPS
    SESSION_COOKIE_SECURE: bool = True  # Secure by default
    SESSION_COOKIE_HTTPONLY: bool = True  # Always True for XSS protection
    SESSION_COOKIE_SAMESITE: str = (
        "Lax"  # Lax=good default, Strict=max security, None=requires Secure
    )
    SESSION_COOKIE_PATH: str = "/"  # Cookie available on all paths
    SESSION_COOKIE_DOMAIN: str | None = None  # None = let browser determine domain

    USER_MODEL: str = "openviper.auth.models.User"
    AUTH_SESSION_ENABLED: bool = True
    SESSION_STORE: str = "database"  # "database" | "redis" | "memory"
    SESSION_ENGINE: str = "django.contrib.sessions.backends.db"  # Database-backed sessions
    AUTH_BACKENDS: tuple[str, ...] = dataclasses.field(
        default_factory=lambda: (
            "openviper.auth.backends.jwt_backend.JWTBackend",
            "openviper.auth.backends.session_backend.SessionBackend",
        )
    )

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
    CSRF_COOKIE_HTTPONLY: bool = True
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

    # ── Monitoring ───────────────────────────────────────────────────────
    ENABLE_MONITORING: bool = False
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_SAMPLE_RATE: float = 0.1

    # ── File Uploads ──────────────────────────────────────────────────────
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

    # ── S3 / Storage ─────────────────────────────────────────────────────
    STATIC_STORAGE: str = "local"  # "local" | "s3"
    MEDIA_STORAGE: str = "local"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_STORAGE_BUCKET_NAME: str = ""

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


# ---------------------------------------------------------------------------
# Lazy global settings proxy
# ---------------------------------------------------------------------------


class _LazySettings:
    """Thread-safe proxy to the active :class:`Settings` instance.

    Loaded lazily on first attribute access.  Use :meth:`configure` for
    programmatic setup before any access occurs.

    Attribute writes for non-underscore names are forbidden after the
    settings are configured; this prevents accidental mutation at runtime.
    """

    def __init__(self) -> None:
        # Use object.__setattr__ to bypass our own __setattr__ guard.
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
                        # Use cached module if available
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
                            logger.warning(
                                "OPENVIPER_SETTINGS_MODULE=%r has no Settings subclass; "
                                "falling back to defaults.",
                                module_path,
                            )
                    except ImportError as exc:
                        logger.warning(
                            "Could not import OPENVIPER_SETTINGS_MODULE=%r: %s; "
                            "falling back to defaults.",
                            module_path,
                            exc,
                        )

            if instance is None:
                instance = Settings()

            # Auto-prepend project app derived from settings module path
            if module_path:
                instance = _auto_include_project_app(instance, module_path)

            # Apply env-var overrides (these take final priority)
            instance = _apply_env_overrides(instance)

            object.__setattr__(self, "_instance", instance)
            object.__setattr__(self, "_configured", True)

    # ------------------------------------------------------------------
    # Attribute access
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        # Called only when normal attribute lookup fails (i.e. for settings
        # attributes not defined directly on _LazySettings itself).
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


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions — no side effects)
# ---------------------------------------------------------------------------


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

    FIX #3: Cache field metadata to avoid repeated dataclasses.fields() calls.
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


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

settings = _LazySettings()

# ---------------------------------------------------------------------------
# Validation & utilities
# ---------------------------------------------------------------------------


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
            # Generate and monkey-patch the SECRET_KEY (frozen dataclass workaround)
            object.__setattr__(s, "SECRET_KEY", generate_secret_key())

    if not s.DATABASE_URL:
        errors.append("DATABASE_URL must be set.")

    if errors:
        raise SettingsValidationError(errors)


def generate_secret_key(length: int = 64) -> str:
    """Generate a cryptographically secure secret key."""
    return secrets.token_urlsafe(length)
