"""Unit tests for openviper.tasks.admin — TaskResult admin configuration."""

from openviper.tasks.admin import TaskResultAdmin


class TestTaskResultAdminAttributes:
    """Test TaskResultAdmin class attributes without requiring full registration."""

    def test_list_display_fields(self):
        """list_display should contain all expected fields."""

        expected = [
            "message_id",
            "actor_name",
            "queue_name",
            "status",
            "retries",
            "enqueued_at",
            "started_at",
            "completed_at",
        ]
        assert TaskResultAdmin.list_display == expected

    def test_search_fields(self):
        """search_fields should allow searching by message_id, actor_name, queue_name."""

        expected = ["message_id", "actor_name", "queue_name"]
        assert TaskResultAdmin.search_fields == expected

    def test_list_filter_fields(self):
        """list_filter should allow filtering by status and timestamps."""

        expected = ["status", "enqueued_at", "started_at", "completed_at"]
        assert TaskResultAdmin.list_filter == expected
