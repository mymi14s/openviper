"""Settings for tp."""

import dataclasses
import os
from typing import TYPE_CHECKING

from openviper.conf.settings import Settings

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "tp"
    DEBUG: bool = bool(int(os.environ.get("DEBUG", "1")))
    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "URL": "sqlite:///db.sqlite3",
            },
        },
    )
    STATIC_ROOT: str = os.environ.get("STATIC_ROOT", "static")
    STATIC_URL: str = os.environ.get("STATIC_URL", "/static/")
    MEDIA_ROOT: str = os.environ.get("MEDIA_ROOT", "media")
    MEDIA_URL: str = os.environ.get("MEDIA_URL", "/media/")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-insecure-key")
    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "blog",
    )
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)

    ADMIN_FOOTER_TITLE: str = "John Admin"
    ADMIN_HEADER_TITLE: str = "John Admin"
    ADMIN_TITLE: str = "John Admin"

    # ── Background Tasks ──────────────────────────────────────────────────
    # Set broker="redis" and broker_url in production.
    TASKS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1,
            "broker": "stub",  # swap to "redis" in production
            "broker_url": "",
            "backend_url": "",
            "logging": {
                "level": "INFO",
                "file": None,
                "database": None,
            },
        }
    )

    # ── Model Events ──────────────────────────────────────────────────────
    # Handlers are resolved once at dispatcher construction time.
    # Keys: "{module}.{ClassName}" of the model.
    # Values: {event_name: [dotted_handler_path, ...]}
    MODEL_EVENTS: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "blog.models.Post": {
                "after_insert": ["blog.events.create_likes"],
                "after_delete": ["blog.events.cleanup_comments"],
            },
            "blog.models.Comment": {
                "after_insert": ["blog.events.notify_post_author"],
            },
        }
    )
