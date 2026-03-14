"""Settings for Ecommerce Clone."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from typing import Any

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "Ecommerce Clone"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    ADMIN_TITLE: str = "Ecommerce Admin"
    ADMIN_HEADER_TITLE: str = "EcommerceClone"
    ADMIN_FOOTER_TITLE: str = "Ecommerce v1.0"
    OPENAPI_TITLE: str = "Ecommerce API"
    OPENAPI_VERSION: str = "1.0.0"
    OPENAPI_DESCRIPTION: str = "API for Amazon-style Ecommerce Platform"

    TEMPLATES_DIR: str = "templates/"

    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./db.sqlite3")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "ecommerce-secret-key-change-in-production")

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "ecommerce_clone",
        "users",
        "products",
        "cart",
        "orders",
        "reviews",
        "chat",
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

    USER_MODEL: str = "users.models.User"
    JWT_SECRET_KEY: str = os.environ.get("SECRET_KEY", "ecommerce-secret-key-change-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE: timedelta = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRE: timedelta = timedelta(days=7)

    MAX_QUERY_ROWS: int = 100_000

    AI_PROVIDERS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "ollama": {
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                "models": {
                    "Granite Code 3B": "granite-code:3b",
                    "Qwen3 4B": "qwen3:4b",
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
