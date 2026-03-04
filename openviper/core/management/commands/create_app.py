"""create_app management command — scaffold a new OpenViper app."""

from __future__ import annotations

import argparse
import os

from openviper.core.management.base import BaseCommand, CommandError

_APP_TEMPLATE = {
    "__init__.py": '"""{{ app_label }} app."""\n\nfrom . import admin  # noqa: F401 - Register admin configuration\n',
    "admin.py": '''"""{{ app_label }} admin configuration."""

from openviper.admin import admin, ModelAdmin, register

# Import your models
# from .models import YourModel


# Register your models with admin here.
# Example:
#
# @register(YourModel)
# class YourModelAdmin(ModelAdmin):
#     list_display = ["id", "name", "created_at"]
#     list_filter = ["created_at"]
#     search_fields = ["name"]
''',
    "models.py": '''"""{{ app_label }} models."""

from openviper.db.models import Model
from openviper.db import fields


# Define your models here.
''',
    "routes.py": '''"""{{ app_label }} routes."""

from openviper.routing import Router

router = Router(prefix="/{{ app_label }}", tags=["{{ app_label }}"])


# Register your routes here.
''',
    "views.py": '''"""{{ app_label }} views."""

from openviper.http.request import Request
from openviper.http.response import JSONResponse


# Define your view handlers here.
''',
    "serializers.py": '''"""{{ app_label }} serializers."""

from openviper.serializers import Serializer


# Define your serializers here.
''',
    "tasks.py": '''"""{{ app_label }} background tasks."""

from openviper.tasks import task


# Define your background tasks here.
''',
    "tests.py": '''"""{{ app_label }} tests."""

import pytest


# Write your tests here.
''',
    os.path.join("migrations", "__init__.py"): "",
}


class Command(BaseCommand):
    help = "Scaffold a new OpenViper application directory."

    aliases = ["create-app"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("name", help="Name of the new app (snake_case recommended)")
        parser.add_argument(
            "--directory",
            "-d",
            default=None,
            help="Target directory (default: current working directory)",
        )

    def handle(self, **options):  # type: ignore[override]
        name: str = options["name"]
        if not name.isidentifier():
            raise CommandError(f"'{name}' is not a valid Python identifier.")

        base_dir = options.get("directory") or os.getcwd()
        app_dir = os.path.join(base_dir, name)

        if os.path.exists(app_dir):
            raise CommandError(f"Directory '{app_dir}' already exists.")

        os.makedirs(os.path.join(app_dir, "migrations"), exist_ok=True)

        for filename, template in _APP_TEMPLATE.items():
            filepath = os.path.join(app_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            content = template.replace("{{ app_label }}", name)
            with open(filepath, "w") as fh:
                fh.write(content)

        self.stdout(self.style_success(f"Created app '{name}' at {app_dir}"))
        self.stdout(self.style_notice(f"Add '{name}' to INSTALLED_APPS in your settings module."))
