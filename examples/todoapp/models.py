"""MiniApp models."""

from openviper.db import Model
from openviper.db.fields import BooleanField, CharField, DateTimeField, IntegerField


class Todo(Model):
    _app_name = "miniapp"

    title = CharField(max_length=255)
    done = BooleanField(default=False)
    owner_id = IntegerField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "miniapp_todos"

    def __str__(self) -> str:
        return self.title or ""
