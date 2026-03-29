from __future__ import annotations

from openviper.db import fields
from openviper.db.models import Model


class CacheEntry(Model):
    """ORM model for database-backed cache storage."""

    class Meta:
        table_name = "openviper_cache_entries"

    key = fields.CharField(max_length=512, unique=True)
    value = fields.TextField()
    expires_at = fields.DateTimeField(null=True)
