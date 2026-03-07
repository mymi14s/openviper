"""OpenViper blog settings for the performance benchmark."""

import dataclasses
import os

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class BlogSettings(Settings):
    PROJECT_NAME: str = "openviper_blog"
    DEBUG: bool = False
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db.sqlite3')}",
    )
    SECRET_KEY: str = "benchmark-key-not-for-production"
    INSTALLED_APPS: tuple[str, ...] = ()
    MIDDLEWARE: tuple[str, ...] = ()
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
