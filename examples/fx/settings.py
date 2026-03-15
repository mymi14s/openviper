"""Flexible project settings.

This project demonstrates viperctl with a root layout where
settings.py, models.py, and admin.py live directly in the
project root -- no package wrapper required.

Usage::

    cd examples/fx
    openviper viperctl makemigrations .
    openviper viperctl migrate .
    openviper viperctl shell
"""

import dataclasses
import os

from openviper.conf.settings import Settings


@dataclasses.dataclass(frozen=True)
class FxSettings(Settings):
    PROJECT_NAME: str = "fx"
    DEBUG: bool = True
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///"
        + os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3"),
    )
    SECRET_KEY: str = "viperctl-demo-key-do-not-use-in-production"
    INSTALLED_APPS: tuple[str, ...] = ()
    MIDDLEWARE: tuple[str, ...] = ()
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
