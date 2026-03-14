"""Unit tests for openviper.tasks.models — TaskResult ORM model."""

from datetime import UTC, datetime, timedelta

from openviper.db import fields
from openviper.tasks.models import TaskResult


class TestTaskResultModel:
    """Test TaskResult model structure and properties."""

    def test_table_name(self):
        """TaskResult should use openviper_task_results table."""
        assert TaskResult.Meta.table_name == "openviper_task_results"

    def test_field_types(self):
        """All fields should have correct types."""
        assert isinstance(TaskResult.id, type(fields.IntegerField()))
        assert isinstance(TaskResult.message_id, type(fields.CharField()))
        assert isinstance(TaskResult.actor_name, type(fields.CharField()))
        assert isinstance(TaskResult.queue_name, type(fields.CharField()))
        assert isinstance(TaskResult.status, type(fields.CharField()))
        assert isinstance(TaskResult.retries, type(fields.IntegerField()))
        assert isinstance(TaskResult.args, type(fields.TextField()))
        assert isinstance(TaskResult.kwargs, type(fields.TextField()))
        assert isinstance(TaskResult.result, type(fields.TextField()))
        assert isinstance(TaskResult.error, type(fields.TextField()))
        assert isinstance(TaskResult.traceback, type(fields.TextField()))
        assert isinstance(TaskResult.enqueued_at, type(fields.DateTimeField()))
        assert isinstance(TaskResult.started_at, type(fields.DateTimeField()))
        assert isinstance(TaskResult.completed_at, type(fields.DateTimeField()))

    def test_repr(self):
        """__repr__ should show key fields."""
        result = TaskResult(message_id="test-123", actor_name="my_actor", status="success")
        repr_str = repr(result)
        assert "TaskResult" in repr_str
        assert "test-123" in repr_str
        assert "my_actor" in repr_str
        assert "success" in repr_str

    def test_duration_ms_with_times(self):
        """duration_ms should calculate execution time when times are set."""
        result = TaskResult(
            message_id="test-123",
            actor_name="my_actor",
            status="success",
            started_at=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 3, 10, 12, 0, 5, tzinfo=UTC),
        )
        assert result.duration_ms == 5000.0

    def test_duration_ms_without_started_at(self):
        """duration_ms should return None when started_at is missing."""
        result = TaskResult(
            message_id="test-123",
            actor_name="my_actor",
            status="success",
            completed_at=datetime.now(UTC),
        )
        assert result.duration_ms is None

    def test_duration_ms_without_completed_at(self):
        """duration_ms should return None when completed_at is missing."""
        result = TaskResult(
            message_id="test-123",
            actor_name="my_actor",
            status="running",
            started_at=datetime.now(UTC),
        )
        assert result.duration_ms is None

    def test_duration_ms_sub_second(self):
        """duration_ms should handle sub-second durations."""
        now = datetime.now(UTC)
        result = TaskResult(
            message_id="test-123",
            actor_name="my_actor",
            status="success",
            started_at=now,
            completed_at=now + timedelta(milliseconds=250),
        )
        assert 240 < result.duration_ms < 260  # Allow small float precision variance
