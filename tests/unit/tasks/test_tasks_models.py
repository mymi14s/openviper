"""Unit tests for openviper.tasks.models (TaskResult)."""

from __future__ import annotations

from datetime import UTC

from openviper.db.fields import CharField, DateTimeField, IntegerField, TextField
from openviper.db.models import Manager, Model
from openviper.tasks.models import TaskResult

# ── Class-level structure ─────────────────────────────────────────────────────


def test_task_result_is_model_subclass():
    assert issubclass(TaskResult, Model)


def test_task_result_meta_table_name():
    assert TaskResult._table_name == "openviper_task_results"


def test_task_result_has_objects_manager():
    assert isinstance(TaskResult.objects, Manager)


def test_task_result_manager_bound_to_correct_model():
    assert TaskResult.objects.model is TaskResult


# ── Field definitions ─────────────────────────────────────────────────────────


def test_task_result_expected_fields_present():
    fields = TaskResult._fields
    expected = {
        "id",
        "message_id",
        "actor_name",
        "queue_name",
        "status",
        "retries",
        "enqueued_at",
        "started_at",
        "completed_at",
    }
    assert expected.issubset(set(fields.keys()))


def test_task_result_id_field():
    field = TaskResult._fields["id"]
    assert isinstance(field, IntegerField)
    assert field.primary_key is True
    assert field.auto_increment is True


def test_task_result_message_id_field():
    field = TaskResult._fields["message_id"]
    assert isinstance(field, CharField)
    assert field.max_length == 64
    assert field.unique is True


def test_task_result_actor_name_field():
    field = TaskResult._fields["actor_name"]
    assert isinstance(field, CharField)
    assert field.max_length == 255


def test_task_result_queue_name_field():
    field = TaskResult._fields["queue_name"]
    assert isinstance(field, CharField)
    assert field.max_length == 100


def test_task_result_status_field():
    field = TaskResult._fields["status"]
    assert isinstance(field, CharField)
    assert field.max_length == 20
    assert field.default == "pending"


def test_task_result_retries_field():
    field = TaskResult._fields["retries"]
    assert isinstance(field, IntegerField)
    assert field.default == 0


def test_task_result_result_field_nullable():
    field = TaskResult._fields["result"]
    assert isinstance(field, TextField)
    assert field.null is True


def test_task_result_error_field_nullable():
    field = TaskResult._fields["error"]
    assert isinstance(field, TextField)
    assert field.null is True


def test_task_result_traceback_field_nullable():
    field = TaskResult._fields["traceback"]
    assert isinstance(field, TextField)
    assert field.null is True


def test_task_result_enqueued_at_field():
    field = TaskResult._fields["enqueued_at"]
    assert isinstance(field, DateTimeField)
    assert field.null is True


def test_task_result_started_at_field():
    field = TaskResult._fields["started_at"]
    assert isinstance(field, DateTimeField)
    assert field.null is True


def test_task_result_completed_at_field():
    field = TaskResult._fields["completed_at"]
    assert isinstance(field, DateTimeField)
    assert field.null is True


# ── Instance creation and defaults ────────────────────────────────────────────


def test_task_result_default_status_is_pending():
    record = TaskResult(message_id="abc", actor_name="send_email", queue_name="default")
    assert record.status == "pending"


def test_task_result_default_retries_is_zero():
    record = TaskResult(message_id="abc", actor_name="send_email", queue_name="default")
    assert record.retries == 0


def test_task_result_id_defaults_to_none():
    record = TaskResult(message_id="abc", actor_name="send_email", queue_name="default")
    assert record.id is None


def test_task_result_init_with_explicit_id():
    record = TaskResult(id=42, message_id="abc", actor_name="send_email", queue_name="high")
    assert record.id == 42


def test_task_result_init_with_all_fields():
    record = TaskResult(
        id=99,
        message_id="msg-1",
        actor_name="process_payment",
        queue_name="critical",
        status="running",
        retries=2,
    )
    assert record.id == 99
    assert record.message_id == "msg-1"
    assert record.actor_name == "process_payment"
    assert record.queue_name == "critical"
    assert record.status == "running"
    assert record.retries == 2


def test_task_result_custom_status():
    record = TaskResult(message_id="x", actor_name="a", queue_name="q", status="success")
    assert record.status == "success"


def test_task_result_pk_property_mirrors_id():
    record = TaskResult(id=7, message_id="x", actor_name="a", queue_name="q")
    assert record.pk == 7


def test_task_result_pk_none_when_id_not_set():
    record = TaskResult(message_id="x", actor_name="a", queue_name="q")
    assert record.pk is None


# ── __repr__ ──────────────────────────────────────────────────────────────────


def test_task_result_repr_contains_class_name():
    record = TaskResult(id=1, message_id="msg-1", actor_name="send_email", queue_name="default")
    assert "TaskResult" in repr(record)


def test_task_result_repr_contains_message_id():
    record = TaskResult(id=5, message_id="msg-5", actor_name="send_email", queue_name="default")
    assert "msg-5" in repr(record)


def test_task_result_repr_contains_status():
    record = TaskResult(
        id=1, message_id="m", actor_name="act", queue_name="default", status="running"
    )
    assert "running" in repr(record)


# ── duration_ms property ──────────────────────────────────────────────────────


def test_task_result_duration_ms_none_when_timestamps_missing():
    record = TaskResult(message_id="x", actor_name="a", queue_name="q")
    assert record.duration_ms is None


def test_task_result_duration_ms_computed_when_both_timestamps_set():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(milliseconds=250)
    record = TaskResult(message_id="x", actor_name="a", queue_name="q")
    record.started_at = start
    record.completed_at = end
    assert abs(record.duration_ms - 250.0) < 1.0


# ── Equality and identity ─────────────────────────────────────────────────────


def test_task_result_equal_same_pk():
    r1 = TaskResult(id=10, message_id="m", actor_name="a", queue_name="q")
    r2 = TaskResult(id=10, message_id="m", actor_name="a", queue_name="q")
    assert r1 == r2


def test_task_result_not_equal_different_pk():
    r1 = TaskResult(id=1, message_id="m", actor_name="a", queue_name="q")
    r2 = TaskResult(id=2, message_id="m", actor_name="a", queue_name="q")
    assert r1 != r2


def test_task_result_not_equal_none_pk():
    r1 = TaskResult(message_id="m", actor_name="a", queue_name="q")
    r2 = TaskResult(message_id="m", actor_name="a", queue_name="q")
    # Two unsaved instances (pk=None) are not considered equal
    assert r1 != r2
