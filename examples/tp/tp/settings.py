"""Settings for tp."""

import dataclasses
import os

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "tp"
    DEBUG: bool = bool(int(os.environ.get("DEBUG", "1")))
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
    STATIC_ROOT: str = os.environ.get("STATIC_ROOT", "static")
    STATIC_URL: str = os.environ.get("STATIC_URL", "/static/")
    MEDIA_ROOT: str = os.environ.get("MEDIA_ROOT", "media")
    MEDIA_URL: str = os.environ.get("MEDIA_URL", "/media/")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-insecure-key")
    INSTALLED_APPS: tuple = (
        "openviper.auth",
        "blog",
    )
    MIDDLEWARE: tuple = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )
    ALLOWED_HOSTS: tuple = ("*",)

    ADMIN_FOOTER_TITLE: str = "John Admin"
    ADMIN_HEADER_TITLE: str = "John Admin"
    ADMIN_TITLE: str = "John Admin"

    # ── Background Tasks ──────────────────────────────────────────────────
    # Set broker="redis" and broker_url in production.
    TASKS: dict = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1,
            "broker": "stub",  # swap to "redis" in production
            "scheduler_enabled": 0,
            "tracking_enabled": 0,
        }
    )

    # ── Model Events ──────────────────────────────────────────────────────
    # Handlers are resolved once at dispatcher construction time.
    # Keys: "{module}.{ClassName}" of the model.
    # Values: {event_name: [dotted_handler_path, ...]}
    MODEL_EVENTS: dict = dataclasses.field(
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
