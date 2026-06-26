"""Settings for robotwit."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta

from openviper.conf.types import ConfigMap
from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "robotwit"
    DEBUG: bool = bool(int(os.environ.get("DEBUG", "1")))
    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
                "OPTIONS": {
                    "URL": os.environ.get("DATABASE_URL"),
                    "ECHO": False,
                    "POOL_SIZE": 5,
                    "MAX_OVERFLOW": 10,
                    "POOL_RECYCLE": 3600,
                },
            },
            "ROUTERS": [],
            "ROUTING": {},
        }
    )
    CACHES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "BACKEND": "openviper.cache.InMemoryCache",
                "OPTIONS": {
                    "ttl": 300,
                },
            },
        }
    )
    ADMIN_SETTINGS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "title": "robotwit Admin",
            "header_title": "robotwit",
            "footer_title": "robotwit Admin",
        }
    )
    SECRET_KEY: str = os.environ.get(
        "SECRET_KEY",
        "AdWNCQye4x01FPf8p1p20o03kLF6wulsD3faGI7WMTo3PqREaxrzqSkdR4y-cJrbQh70hQbrTOEZrluMGlWSeg",
    )
    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "openviper.tasks",
        "agents",
        "tweets",
        "timeline",
        "notifications",
        "realtime",
    )
    MIDDLEWARE: tuple[str, ...] = (
        "realtime.middleware.WebSocketMiddleware",
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )
    STATIC_ROOT: str = os.environ.get("STATIC_ROOT", "static")
    STATIC_URL: str = os.environ.get("STATIC_URL", "/static/")
    MEDIA_ROOT: str = os.environ.get("MEDIA_ROOT", "media")
    MEDIA_URL: str = os.environ.get("MEDIA_URL", "/media/")
    TEMPLATES_DIR: str = "templates"
    USER_MODEL: str = "agents.models.Agent"

    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = timedelta(hours=24)
    SESSION_COOKIE_SECURE: bool = bool(int(os.environ.get("SESSION_COOKIE_SECURE", "0")))
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_PATH: str = "/"
    SESSION_COOKIE_DOMAIN: str | None = None

    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")

    TASKS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1,
            "broker": os.environ.get("TASKS_BROKER", "stub"),
            "broker_url": os.environ.get("REDIS_URL", ""),
            "backend_url": os.environ.get("REDIS_BACKEND_URL", ""),
            "logging": {
                "level": "INFO",
                "file": 1,
                "database": None,
            },
        }
    )

    AI_PROVIDERS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "ollama": {
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                "model": {
                    "smollm2": "smollm2:135m",
                },
                "temperature": 0.8,
            },
        }
    )

    ENABLE_AI_PROVIDERS: bool = True
    AI_DEFAULT_MODEL: str = os.environ.get("AI_DEFAULT_MODEL", "smollm2:135m")

    ROBOTWIT_LIMITS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "max_concurrent_agent_tasks": 3,
            "global_post_rate_limit": 5,
            "min_interval_between_posts": 12,
            "scheduler_interval": 120,
            "default_post_frequency": 30,
            "default_daily_post_limit": 10,
            "default_daily_engagement_limit": 50,
            "default_cooldown_seconds": 60,
            "min_content_length": 10,
            "max_content_length": 280,
            "similarity_threshold": 0.7,
            "moderation_enabled": False,
        }
    )

    ROBOTWIT_AGENT_GENERATION: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default_model": "smollm2:135m",
            "default_temperature": 0.8,
            "avatar_count": 50,
            "username_prefix": "agent",
            "min_post_frequency": 20,
            "max_post_frequency": 60,
            "min_daily_post_limit": 5,
            "max_daily_post_limit": 15,
        }
    )
