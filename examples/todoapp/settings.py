"""MiniApp settings."""

import dataclasses
import os
from datetime import timedelta

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class MiniAppSettings(Settings):
    PROJECT_NAME: str = "miniapp"
    DEBUG: bool = bool(int(os.environ.get("DEBUG", "1")))
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    INSTALLED_APPS: tuple = ("openviper.auth", "openviper.admin")

    MIDDLEWARE: tuple = (
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )

    ALLOWED_HOSTS: tuple = ("*",)
    TEMPLATES_DIR: str = "templates"

    SESSION_COOKIE_NAME: str = "sessionid"
    SESSION_TIMEOUT: timedelta = timedelta(hours=24)
