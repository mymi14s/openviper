"""MiniApp settings."""

from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from openviper.conf.settings import Settings

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap


@dataclasses.dataclass(frozen=True)
class MiniAppSettings(Settings):
    PROJECT_NAME: str = "miniapp"
    DEBUG: bool = bool(int(os.environ.get("DEBUG", 0)))
    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "URL": os.environ.get("DATABASE_URL"),
            },
        },
    )
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    INSTALLED_APPS: tuple[str, ...] = ("openviper.auth", "openviper.admin")

    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )

    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    )
    TEMPLATES_DIR: str = "templates"

    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_TIMEOUT: timedelta = timedelta(hours=24)
