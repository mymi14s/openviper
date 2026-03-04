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
    SECRET_KEY: str = "INSECURE-CHANGE-ME"

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

    # ── Authentication ────────────────────────────────────────────────────
    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")
    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=1))
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    USER_MODEL: str = "openviper.auth.models.User"

    # ── JWT ───────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE: timedelta = dataclasses.field(
        default_factory=lambda: timedelta(hours=24)
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
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOWED_METHODS: tuple[str, ...] = (
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    )
    CORS_ALLOWED_HEADERS: tuple[str, ...] = ("*",)
    CORS_MAX_AGE: int = 600

    # ── Static Files ──────────────────────────────────────────────────────
    STATIC_URL: str = "/static/"
    STATIC_ROOT: str = "./static/"
    STATICFILES_DIRS: tuple[str, ...] = ("static/",)
    MEDIA_URL: str = "/media/"
    MEDIA_ROOT: str = "./media/"

    # ── Templates ─────────────────────────────────────────────────────────
    TEMPLATES_DIR: str = "templates/"
    TEMPLATE_AUTO_RELOAD: bool = True

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "text" | "json"

    # ── Email ─────────────────────────────────────────────────────────────
    EMAIL_BACKEND: str = ""  # "console" | "smtp" | "memory"
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_USE_TLS: bool = True
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_FROM: str = ""

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
    RATE_LIMIT_REQUESTS: int = 1_000_000
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

    def as_dict(self) -> dict[str, Any]:
        """Return all settings as a plain dict (shallow copy)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

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

            # Load .env if available
            if _HAS_DOTENV:
                _load_dotenv(dotenv_path=".env", override=False)

            module_path = os.environ.get("OPENVIPER_SETTINGS_MODULE", "")
            instance: Settings | None = None

            if module_path:
                try:
                    mod = importlib.import_module(module_path)
                    # Find a frozen dataclass subclass of Settings
                    for attr_name in dir(mod):
                        obj = getattr(mod, attr_name, None)
                        if (
                            isinstance(obj, type)
                            and issubclass(obj, Settings)
                            and obj is not Settings
                            and dataclasses.is_dataclass(obj)
                        ):
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
    """Return a new :class:`Settings` with env-var overrides applied."""
    overrides: dict[str, Any] = {}
    for f in dataclasses.fields(instance):
        if not f.name.isupper():
            continue
        raw = os.environ.get(f.name)
        if raw is None:
            continue
        current = getattr(instance, f.name)
        casted = _cast_env_value(current, raw)
        if casted is not None:
            overrides[f.name] = casted
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

    if env == "production":
        if s.DEBUG:
            errors.append("DEBUG must be False in production.")
        if not s.SECRET_KEY or s.SECRET_KEY in (
            "INSECURE-CHANGE-ME",
            "dev-insecure-key",
        ):
            errors.append("SECRET_KEY must be set to a strong random value in production.")
        elif len(s.SECRET_KEY) < 50:
            errors.append("SECRET_KEY must be at least 50 characters long in production.")
        if not s.SECURE_COOKIES:
            errors.append("SECURE_COOKIES must be True in production.")
        if not s.ALLOWED_HOSTS:
            errors.append("ALLOWED_HOSTS must contain at least one entry in production.")

    if not s.DATABASE_URL:
        errors.append("DATABASE_URL must be set.")

    if errors:
        raise SettingsValidationError(errors)


def generate_secret_key(length: int = 64) -> str:
    """Generate a cryptographically secure secret key."""
    return secrets.token_urlsafe(length)
