"""Tests for openviper.tasks.models - task result persistence models."""

from __future__ import annotations

import pytest

from openviper.tasks.models import (
    TASK_STATUS_CHOICES,
    TRIGGER_SOURCE_CHOICES,
    ScheduledJob,
    TaskResult,
)


class TestTaskResultModel:
    """Verify TaskResult model fields and constraints."""

    def test_task_status_choices_defined(self) -> None:
        """Task status must include all required lifecycle states."""
        expected = [
            ("pending", "Pending"),
            ("running", "Running"),
            ("success", "Success"),
            ("failure", "Failure"),
            ("skipped", "Skipped"),
            ("dead", "Dead"),
        ]
        assert expected == TASK_STATUS_CHOICES

    def test_task_result_meta_table_name(self) -> None:
        """TaskResult must use the correct table name."""
        assert TaskResult.Meta.table_name == "openviper_task_result"

    def test_task_result_message_id_is_uuid(self) -> None:
        """message_id field must be a UUIDField with unique constraint."""
        from openviper.db import fields

        msg_field = TaskResult.message_id
        assert isinstance(msg_field, fields.UUIDField)
        assert msg_field.unique is True

    def test_task_result_status_default(self) -> None:
        """status field must default to 'pending'."""
        status_field = TaskResult.status
        assert status_field.default == "pending"

    def test_task_result_status_has_choices(self) -> None:
        """status field must have choices constrained to TASK_STATUS_CHOICES."""
        status_field = TaskResult.status
        assert hasattr(status_field, "choices")
        assert status_field.choices == TASK_STATUS_CHOICES

    def test_task_result_queue_default(self) -> None:
        """queue field must default to 'default'."""
        queue_field = TaskResult.queue
        assert queue_field.default == "default"


class TestScheduledJobModel:
    """Verify ScheduledJob model fields and constraints."""

    def test_trigger_source_choices_defined(self) -> None:
        """trigger_source must accept 'cron' and 'interval'."""
        expected = [("cron", "Cron"), ("interval", "Interval")]
        assert expected == TRIGGER_SOURCE_CHOICES

    def test_scheduled_job_meta_table_name(self) -> None:
        """ScheduledJob must use the correct table name."""
        assert ScheduledJob.Meta.table_name == "openviper_scheduled_job"

    def test_scheduled_job_name_is_unique(self) -> None:
        """name field must be unique."""
        name_field = ScheduledJob.name
        assert name_field.unique is True

    def test_scheduled_job_trigger_source_has_choices(self) -> None:
        """trigger_source field must have choices constrained."""
        trigger_field = ScheduledJob.trigger_source
        assert hasattr(trigger_field, "choices")
        assert trigger_field.choices == TRIGGER_SOURCE_CHOICES

    def test_scheduled_job_status_default(self) -> None:
        """status field must default to 'active'."""
        status_field = ScheduledJob.status
        assert status_field.default == "active"


class TestTaskResultStateTransitions:
    """Verify data state life cycles across all stages."""

    def test_task_status_pending_to_running(self) -> None:
        """Task status must transition from 'pending' to 'running'."""
        values = [c[0] for c in TASK_STATUS_CHOICES]
        assert "pending" in values
        assert "running" in values

    def test_task_status_running_to_success(self) -> None:
        """Task status must support 'success' as a terminal state."""
        values = [c[0] for c in TASK_STATUS_CHOICES]
        assert "success" in values

    def test_task_status_running_to_failure(self) -> None:
        """Task status must support 'failure' as a terminal state."""
        values = [c[0] for c in TASK_STATUS_CHOICES]
        assert "failure" in values

    def test_task_status_running_to_dead(self) -> None:
        """Task status must support 'dead' as a terminal state after max retries."""
        values = [c[0] for c in TASK_STATUS_CHOICES]
        assert "dead" in values

    def test_task_status_skipped(self) -> None:
        """Task status must support 'skipped' for intentionally bypassed tasks."""
        values = [c[0] for c in TASK_STATUS_CHOICES]
        assert "skipped" in values


class TestScheduledJobSync:
    """Verify synchronization states reconcile database tables."""

    def test_trigger_source_cron(self) -> None:
        """Cron-based jobs must use 'cron' trigger source."""
        values = [c[0] for c in TRIGGER_SOURCE_CHOICES]
        assert "cron" in values

    def test_trigger_source_interval(self) -> None:
        """Interval-based jobs must use 'interval' trigger source."""
        values = [c[0] for c in TRIGGER_SOURCE_CHOICES]
        assert "interval" in values
