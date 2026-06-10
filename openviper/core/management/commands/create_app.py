"""Scaffold a new OpenViper application directory."""

from __future__ import annotations

import argparse
import os

from openviper.core.management.base import BaseCommand, CommandError

APP_TEMPLATE: dict[str, str] = {
    "__init__.py": '"""{{ app_label }} app."""\n',
    "admin.py": '''"""{{ app_label }} admin configuration."""

#from openviper.admin import ModelAdmin, register

# @register(YourModel)
# class YourModelAdmin(ModelAdmin):
#     list_display = ["id", "title", "created_at"]
#     list_filter = ["created_at"]
#     search_fields = ["title"]
#     ordering = ["-created_at"]
''',
    "models.py": '''"""{{ app_label }} models."""

#from openviper.db.models import Model
#from openviper.db import fields

# class Article(Model):
#     title = fields.CharField(max_length=255)
#     body = fields.TextField()
#     published = fields.BooleanField(default=False)
#     created_at = fields.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         ordering = ["-created_at"]
''',
    "routes.py": '''"""{{ app_label }} routes."""

#from openviper.routing import Router
#from {{ app_label }}.views import list_items, create_item

#router = Router(prefix="")

# router.add("/items", list_items, methods=["GET"])
# router.add("/items", create_item, methods=["POST"])
''',
    "views.py": '''"""{{ app_label }} views."""

#from openviper.http.response import JSONResponse

# async def list_items(request):
#     return JSONResponse({"items": []})
#
# async def create_item(request):
#     data = await request.json()
#     return JSONResponse(data, status_code=201)
''',
    "serializers.py": '''"""{{ app_label }} serializers."""

#from openviper.serializers import Serializer, ModelSerializer

# class ItemSerializer(Serializer):
#     name: str
#     description: str | None = None
''',
    "tasks.py": '''"""{{ app_label }} background tasks."""

#from openviper.tasks import actor, periodic

# @actor(queue_name="default", max_retries=3)
# async def process_item(item_id: int) -> None:
#     pass
''',
    "events.py": '''"""{{ app_label }} model events."""

#from openviper.db.events import model_event

# @model_event.trigger("{{ app_label }}.models.Article.after_insert")
# async def on_article_created(instance, *, event: str) -> None:
#     pass
''',
    "lifecycle.py": '''"""{{ app_label }} lifecycle hooks."""


def ready() -> None:
    """Post-discovery setup hook."""
''',
    "tests.py": '''"""{{ app_label }} tests."""

# from openviper.testing import OpenViperTestCase
#
# class TestItem(OpenViperTestCase):
#     async def test_list_items(self):
#         response = await self.client.get("/{{ app_label }}/items")
#         self.assertEqual(response.status_code, 200)
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

    def handle(self, **options) -> None:  # type: ignore[override]
        name: str = options["name"]
        if not name.isidentifier():
            raise CommandError(f"'{name}' is not a valid Python identifier.")

        base_dir = options.get("directory") or os.getcwd()
        app_dir = os.path.join(base_dir, name)

        if os.path.exists(app_dir):
            raise CommandError(f"Directory '{app_dir}' already exists.")

        os.makedirs(os.path.join(app_dir, "migrations"), exist_ok=True)

        for filename, template in APP_TEMPLATE.items():
            filepath = os.path.join(app_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            content = template.replace("{{ app_label }}", name)
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)

        self.stdout(self.style_success(f"Created app '{name}' at {app_dir}"))
        self.stdout(self.style_notice(f"Add '{name}' to INSTALLED_APPS in your settings module."))
