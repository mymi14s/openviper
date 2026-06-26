"""Settings for ai_smart_recipe_generator."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from openviper.conf.settings import Settings

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "AI Smart Recipe Generator"
    DEBUG: bool = int(os.environ.get("DEBUG", 0))
    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "URL": os.environ.get("DATABASE_URL"),
            },
        },
    )
    SECRET_KEY: str = os.environ.get(
        "SECRET_KEY",
        "dev-secret-key-change-in-production",
    )

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "recipe_generator_app",
    )
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
    STATIC_ROOT: str = os.environ.get("STATIC_ROOT", "static")
    STATIC_URL: str = os.environ.get("STATIC_URL", "/static/")
    MEDIA_ROOT: str = os.environ.get("MEDIA_ROOT", "media")
    MEDIA_URL: str = os.environ.get("MEDIA_URL", "/media/")

    TEMPLATES_DIR: str = "templates"

    # ── Authentication & Session Settings ─────────────────────────────────
    PASSWORD_HASHERS: tuple[str, ...] = ("argon2", "bcrypt")

    # Session Configuration (environment-aware for dev/prod)
    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = timedelta(hours=8)

    # Cookie security settings - automatically adjust based on DEBUG mode
    # In development (DEBUG=True): Secure=False, SameSite=Lax (works with HTTP)
    # In production (DEBUG=False): Secure=True, SameSite=Strict (requires HTTPS)
    SESSION_COOKIE_SECURE: bool = not os.environ.get("DEBUG")
    SESSION_COOKIE_HTTPONLY: bool = True  # Always True for security
    SESSION_COOKIE_SAMESITE: str = "Strict" if not os.environ.get("DEBUG") else "Lax"
    SESSION_COOKIE_PATH: str = "/"
    SESSION_COOKIE_DOMAIN: str | None = None  # Let browser set domain (works for localhost)

    # AI Configuration
    AI_PROVIDERS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "ollama": {
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                "models": {
                    "Granite Code 3B": "granite-code:3b",
                    "Llama 3": "llama3",
                    "Mistral": "mistral",
                    "Code Llama": "codellama",
                },
            },
            "gemini": {
                "api_key": os.environ.get("GEMINI_API_KEY"),
                "model": {
                    "GEMINI 2.5 FLASH": "gemini-2.5-flash",
                    "GEMINI 3 PRO PREVIEW": "gemini-3-pro-preview",
                    "GEMINI 3 FLASH PREVIEW": "gemini-3-flash-preview",
                    "GEMINI 3.1 PRO PREVIEW": "gemini-3.1-pro-preview",
                    "GEMINI 3.1 PRO PREVIEW CUSTOMTOOLS": "gemini-3.1-pro-preview-customtools",
                    "GEMINI 3.1 FLASH LITE PREVIEW": "gemini-3.1-flash-lite-preview",
                    "GEMINI 3 PRO IMAGE PREVIEW": "gemini-3-pro-image-preview",
                },
                "embed_model": "models/text-embedding-004",
                "temperature": 1.0,
                "max_output_tokens": 2048,
                "candidate_count": 1,
                "top_p": 0.95,
                "top_k": 40,
            },
        }
    )

    # Default AI model for recipe generation
    AI_DEFAULT_MODEL: str = os.environ.get("AI_DEFAULT_MODEL", "llama3")

    # # Background Tasks
    # TASKS: ConfigMap = dataclasses.field(
    #     default_factory=lambda: {
    #         "enabled": 1,
    #         "broker": "redis",
    #         "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    #         "backend_url": os.environ.get("REDIS_BACKEND_URL", ""),
    #         "logging": {
    #             "level": "DEBUG",
    #             "file": {
    #                 "log_dir": "logs",
    #                 "file_name": "tasks.log",
    #                 "log_format": "json",
    #                 "max_size": 10,
    #             },
    #             "database": {
    #                 "task": 1,
    #                 "periodic": 1,
    #             },
    #         },
    #     }
    # )

    # # Model events configuration: maps "app.model" to event hooks to lists of
    # # "app.events.func" paths.
    # MODEL_EVENTS: ConfigMap = dataclasses.field(
    #     default_factory=lambda: {
    #         "posts.models.Post": {
    #             "after_insert": ["posts.events.create_likes"],
    #             "after_delete": ["posts.events.cleanup_comments"],
    #             "on_update": ["posts.events.handle_post_update"],
    #         },
    #     }
    # )
