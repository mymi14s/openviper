"""Change history tracking for admin panel.

Provides audit logging for all create, update, and delete operations
performed through the admin interface.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from openviper.db.fields import CharField, DateTimeField, IntegerField, TextField
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
    object_id = IntegerField(db_index=True)
    object_repr = CharField(max_length=255)
    action = CharField(max_length=10)  # add, change, delete
    changed_fields = TextField(null=True)  # JSON of changed fields
    changed_by_id = IntegerField(null=True, db_index=True)
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
        cls, model_name: str, object_id: int, limit: int = 50
    ) -> list[ChangeHistory]:
        """Get change history for a specific object.

        Args:
            model_name: Name of the model.
            object_id: ID of the object.
            limit: Maximum records to return.

        Returns:
            List of ChangeHistory records.
        """
        # This will be called as async in views
        return (
            cls.objects.filter(model_name=model_name, object_id=object_id)
            .order_by("-change_time")
            .limit(limit)
        )


async def log_change(
    model_name: str,
    object_id: int,
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
        user_id = getattr(user, "id", None) or getattr(user, "pk", None)
        username = getattr(user, "username", None) or str(user)

    changed_fields_json = None
    if changes:
        changed_fields_json = json.dumps(changes, default=str)

    record = await ChangeHistory.objects.create(
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr or f"{model_name} #{object_id}",
        action=action,
        changed_fields=changed_fields_json,
        changed_by_id=user_id,
        changed_by_username=username,
        change_message=message,
    )
    return record


async def get_change_history(
    model_name: str, object_id: int, limit: int = 50
) -> list[ChangeHistory]:
    """Get change history for an object.

    Args:
        model_name: Name of the model.
        object_id: ID of the object.
        limit: Maximum records to return.

    Returns:
        List of ChangeHistory records, most recent first.
    """
    return (
        await ChangeHistory.objects.filter(model_name=model_name, object_id=object_id)
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
    all_keys = set(old_data.keys()) | set(new_data.keys())

    for key in all_keys:
        # Skip sensitive fields to prevent exposure in history logs
        if key in SENSITIVE_FIELDS or any(s in key.lower() for s in SENSITIVE_FIELDS):
            continue

        old_val = old_data.get(key)
        new_val = new_data.get(key)

        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}

    return changes
