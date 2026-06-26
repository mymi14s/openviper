"""Flexible project models.

Demonstrates a root-layout project where models.py sits
directly in the project directory (no app package needed).
"""

from openviper.db import Model
from openviper.db.fields import BooleanField, CharField, DateTimeField, TextField


class Note(Model):
    _app_name = "fx"

    title = CharField(max_length=200)
    body = TextField(null=True)
    pinned = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "fx_notes"

    def __str__(self) -> str:
        return self.title or ""


class Tag(Model):
    _app_name = "fx"

    name = CharField(max_length=50)
    color = CharField(max_length=7, default="#3b82f6")

    class Meta:
        table_name = "fx_tags"

    def __str__(self) -> str:
        return self.name or ""
