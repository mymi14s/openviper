"""Settings for AI Moderation Platform."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from typing import Any

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "AI Moderation Platform"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    ADMIN_TITLE: str = "Moderation Admin"
    ADMIN_HEADER_TITLE: str = "ModPlatform"
    ADMIN_FOOTER_TITLE: str = "AI Moderation v1.0"
    OPENAPI_TITLE: str = "AI Moderation API"
    OPENAPI_VERSION: str = "1.0.0"
    OPENAPI_DESCRIPTION: str = "API for AI Moderation Platform"

    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "")

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.tasks",
        "users",
        "posts",
        "moderation",
        "frontend",
    )

    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.SecurityMiddleware",
        "openviper.middleware.AuthenticationMiddleware",
        "openviper.middleware.CORSMiddleware",
    )

    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    )

    # JWT Configuration
    USER_MODEL: str = "users.models.User"
    JWT_SECRET_KEY: str = os.environ.get("SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE: timedelta = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRE: timedelta = timedelta(days=7)

    # AI Configuration
    # Each provider entry is auto-loaded by ProviderRegistry on first access.
    # The "models" / "model" dict values are the model IDs that get registered
    # for O(1) routing, e.g. model_router.set_model("granite-code:3b") will
    # automatically route to the Ollama provider.
    AI_PROVIDERS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "ollama": {
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                "models": {
                    "default": "granite-code:3b",
                    "Granite Code 3B": "granite-code:3b",
                    "Llama 3": "llama3",
                    "Mistral": "mistral",
                    "Code Llama": "codellama",
                },
            },
            "gemini": {
                "api_key": os.environ.get("GEMINI_API_KEY"),
                "model": {
                    "default": "gemini-2.0-flash",
                    "Gemini 2.0 Flash": "gemini-2.0-flash",
                    "Gemini 1.5 Flash": "gemini-1.5-flash",
                    "Gemini 1.5 Pro": "gemini-1.5-pro",
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

    # Moderation Configuration
    AUTO_MODERATE: bool = True
    MODERATION_THRESHOLD: float = 0.7

    # Background Tasks
    TASKS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1,
            "scheduler_enabled": 1,
            "tracking_enabled": 1,
            "log_to_file": 1,
            "log_level": "DEBUG",
            "log_format": "json",
            "log_dir": "logs",
            "broker": "redis",
            "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        }
    )

    # Model events configuration: maps "app.model" to event hooks to lists of "app.events.func" paths.
    MODEL_EVENTS: dict = dataclasses.field(
        default_factory=lambda: {
            "posts.models.Post": {
                "after_insert": ["posts.events.create_likes"],
                "after_delete": ["posts.events.cleanup_comments"],
                "on_update": ["posts.events.handle_post_update"],
            },
            "users.models.User": {
                "on_update": ["users.events.send_email"],
            },
        }
    )
