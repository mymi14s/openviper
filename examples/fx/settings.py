"""Flexible project settings.

This project demonstrates viperctl with a root layout where
settings.py, models.py, and admin.py live directly in the
project root -- no package wrapper required.

Usage::

    cd examples/fx
    openviper viperctl makemigrations .
    openviper viperctl migrate .
    openviper viperctl console
"""

import dataclasses
import os
from typing import TYPE_CHECKING

from openviper.conf.settings import Settings

if TYPE_CHECKING:
    from openviper.conf.types import ConfigMap


@dataclasses.dataclass(frozen=True)
class FxSettings(Settings):
    PROJECT_NAME: str = "fx"
    DEBUG: bool = True
    DATABASES: ConfigMap = dataclasses.field(
        default_factory=lambda: {
            "default": {
                "URL": os.environ.get("DATABASE_URL"),
            },
        },
    )
    SECRET_KEY: str = "viperctl-demo-key-do-not-use-in-production"  # noqa: S105
    INSTALLED_APPS: tuple[str, ...] = ()
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
    )
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
