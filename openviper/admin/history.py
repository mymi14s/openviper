"""Change history tracking for admin panel.

Provides audit logging for all create, update, and delete operations
performed through the admin interface.
"""

from __future__ import annotations

import datetime as _dt
import json
from enum import StrEnum
from typing import Any

from openviper.db.fields import CharField, DateTimeField, TextField
from openviper.db.models import Model

# Fields that should never be tracked in history for security/privacy
SENSITIVE_FIELDS = {
    "password",
    "token",
    "secret",
    "key",
    "api_key",
    "access_token",
    "refresh_token",
}


class ChangeAction(StrEnum):
    """Type of change made to an object."""

    ADD = "add"
    CHANGE = "change"
    DELETE = "delete"


class ChangeHistory(Model):
    """Model for tracking changes to admin-managed objects.

    Stores a record of every create, update, and delete operation
    performed through the admin interface.
    """

    model_name = CharField(max_length=100, db_index=True)
    object_id = CharField(max_length=255, db_index=True)
    object_repr = CharField(max_length=255)
    action = CharField(max_length=10)  # add, change, delete
    changed_fields = TextField(null=True)  # JSON of changed fields
    changed_by_id = CharField(max_length=255, null=True, db_index=True)
    changed_by_username = CharField(max_length=150, null=True)
    change_time = DateTimeField(auto_now_add=True)
    change_message = TextField(null=True)

    class Meta:
        table_name = "admin_changehistory"

    def __str__(self) -> str:
        return f"{self.action} {self.model_name} #{self.object_id}"

    def get_changed_fields_dict(self) -> dict[str, Any]:
        """Parse changed_fields JSON to dict.

        Returns:
            Dict of field changes.
        """
        if not self.changed_fields:
            return {}
        try:
            return json.loads(self.changed_fields)
        except json.JSONDecodeError:
            return {}

    @classmethod
    def get_for_object(
        cls, model_name: str, object_id: str | int, limit: int = 50
    ) -> list[ChangeHistory]:
        """Get change history for a specific object.

        Args:
            model_name: Name of the model.
            object_id: ID of the object.
            limit: Maximum records to return.

        Returns:
            List of ChangeHistory records.
        """
        # Convert object_id to string for querying VARCHAR field
        object_id_str = str(object_id)
        # This will be called as async in views
        return (
            cls.objects.filter(model_name=model_name, object_id=object_id_str)
            .order_by("-change_time")
            .limit(limit)
        )


async def log_change(
    model_name: str,
    object_id: str | int,
    action: ChangeAction | str,
    changes: dict[str, Any] | None = None,
    user: Any = None,
    object_repr: str | None = None,
    message: str | None = None,
) -> ChangeHistory:
    """Log a change to the history.

    Args:
        model_name: Name of the model that was changed.
        object_id: ID of the object that was changed.
        action: Type of change (add, change, delete).
        changes: Dict of field changes (old -> new values).
        user: The user who made the change.
        object_repr: String representation of the object.
        message: Optional change message.

    Returns:
        The created ChangeHistory record.
    """
    if isinstance(action, ChangeAction):
        action = action.value

    user_id = None
    username = None
    if user is not None:
        _uid = getattr(user, "id", None) or getattr(user, "pk", None)
        user_id = str(_uid) if _uid is not None else None
        username = getattr(user, "username", None) or str(user)

    changed_fields_json = None
    if changes:
        changed_fields_json = json.dumps(changes, default=str)

    # Convert object_id to string for storage in VARCHAR field
    object_id_str = str(object_id)

    record = await ChangeHistory.objects.create(
        model_name=model_name,
        object_id=object_id_str,
        object_repr=object_repr or f"{model_name} #{object_id}",
        action=action,
        changed_fields=changed_fields_json,
        changed_by_id=user_id,
        changed_by_username=username,
        change_message=message,
    )
    return record


async def get_change_history(
    model_name: str, object_id: str | int, limit: int = 50
) -> list[ChangeHistory]:
    """Get change history for an object.

    Args:
        model_name: Name of the model.
        object_id: ID of the object.
        limit: Maximum records to return.

    Returns:
        List of ChangeHistory records, most recent first.
    """
    # Convert object_id to string for querying VARCHAR field
    object_id_str = str(object_id)
    return (
        await ChangeHistory.objects.filter(model_name=model_name, object_id=object_id_str)
        .order_by("-change_time")
        .limit(limit)
        .all()
    )


async def get_recent_activity(limit: int = 20) -> list[ChangeHistory]:
    """Get recent change activity across all models.

    Args:
        limit: Maximum records to return.

    Returns:
        List of recent ChangeHistory records.
    """
    return await ChangeHistory.objects.order_by("-change_time").limit(limit).all()


def _normalize_for_compare(val: Any) -> Any:
    """Normalize a value for change comparison.

    Converts datetime/date/time objects to ISO strings so that comparisons
    between ORM-returned objects and coerced request values don't raise
    TypeError (e.g. aware vs naive datetime).
    """
    if isinstance(val, (_dt.datetime, _dt.date, _dt.time)):
        return val.isoformat()
    return val


def compute_changes(
    old_data: dict[str, Any], new_data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compute the differences between old and new data.

    Args:
        old_data: Previous field values.
        new_data: New field values.

    Returns:
        Dict mapping field names to {"old": value, "new": value}.
    """
    changes = {}
    # Only track fields that were actually sent in the update (new_data).
    # This avoids logging fields as 'None' if they were just omitted from a partial update.
    for key in new_data:
        # Skip sensitive fields to prevent exposure in history logs
        if key in SENSITIVE_FIELDS or any(s in key.lower() for s in SENSITIVE_FIELDS):
            continue

        old_val = old_data.get(key)
        new_val = new_data.get(key)

        # Normalize comparison: treat None and empty string as equivalent for most fields
        # to avoid noise in history logs when a field is cleared or missing.
        is_empty_old = old_val is None or old_val == ""
        is_empty_new = new_val is None or new_val == ""

        if is_empty_old and is_empty_new:
            continue

        if _normalize_for_compare(old_val) != _normalize_for_compare(new_val):
            changes[key] = {"old": old_val, "new": new_val}

    return changes
