"""Chat models."""

from __future__ import annotations

from openviper.db import Model
from openviper.db.fields import CharField, DateTimeField, TextField, UUIDField


class ChatCache(Model):
    """Cached AI answers keyed by a hash of the normalised question."""

    _app_name = "chat"

    id = UUIDField(primary_key=True, auto=True)
    question_hash = CharField(max_length=64, unique=True)
    question = TextField()
    answer = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "chat_cache"

    def __str__(self) -> str:
        return (self.question or "")[:50]


class ProductSummary(Model):
    """AI-generated summary of a product for chat context retrieval."""

    _app_name = "chat"

    id = UUIDField(primary_key=True, auto=True)
    product_id = CharField(max_length=36)
    summary = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "chat_product_summary"

    def __str__(self) -> str:
        return f"summary:{self.product_id}"
