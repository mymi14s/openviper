"""Unit tests for openviper.tasks.decorators — @task decorator."""

from unittest.mock import MagicMock, patch

from openviper.tasks.decorators import task


class TestTaskDecorator:
    """Test @task decorator functionality."""

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_creates_actor(self, mock_dramatiq_actor, mock_get_broker):
        """@task should create a Dramatiq actor."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        def my_task():
            pass

        original_fn = my_task
        result = task()(my_task)

        # Should call get_broker to ensure broker is initialized
        mock_get_broker.assert_called_once()

        # Should create actor via dramatiq.actor
        mock_dramatiq_actor.assert_called_once()
        args, kwargs = mock_dramatiq_actor.call_args
        assert args[0] is original_fn

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_defaults(self, mock_dramatiq_actor, mock_get_broker):
        """@task() should use default parameters."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task()
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["queue_name"] == "default"
        assert kwargs["priority"] == 0
        assert kwargs["max_retries"] == 3
        assert kwargs["min_backoff"] == 15_000
        assert kwargs["max_backoff"] == 300_000
        assert "time_limit" not in kwargs  # Only set when explicitly provided

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_custom_queue(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept custom queue_name."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(queue_name="emails")
        def send_email():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["queue_name"] == "emails"

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_custom_retries(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept custom max_retries."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(max_retries=10)
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["max_retries"] == 10

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_priority(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept custom priority."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(priority=10)
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["priority"] == 10

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_backoff(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept custom backoff values."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(min_backoff=1000, max_backoff=60_000)
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["min_backoff"] == 1000
        assert kwargs["max_backoff"] == 60_000

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_time_limit(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept time_limit."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(time_limit=30_000)
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["time_limit"] == 30_000

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_custom_actor_name(self, mock_dramatiq_actor, mock_get_broker):
        """@task should accept custom actor_name."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(actor_name="custom.name")
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["actor_name"] == "custom.name"

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_uses_function_name_as_default_actor_name(
        self, mock_dramatiq_actor, mock_get_broker
    ):
        """@task should use function __name__ as default actor_name."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task()
        def my_custom_function():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["actor_name"] == "my_custom_function"

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_adds_delay_alias(self, mock_dramatiq_actor, mock_get_broker):
        """@task should add .delay() as an alias for .send()."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_actor_instance.send = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task()
        def my_task():
            pass

        # .delay should be the same as .send
        assert my_task.delay is my_task.send

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    @patch("openviper.tasks.decorators.logger")
    def test_decorator_logs_registration(self, mock_logger, mock_dramatiq_actor, mock_get_broker):
        """@task should log the registration."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(queue_name="myqueue", max_retries=5)
        def my_task():
            pass

        # Should have logged the registration
        assert mock_logger.debug.called
        call_args = mock_logger.debug.call_args[0]
        assert "Registered task" in call_args[0]

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_with_async_function(self, mock_dramatiq_actor, mock_get_broker):
        """@task should work with async functions."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task()
        async def my_async_task():
            pass

        # Should still create an actor
        mock_dramatiq_actor.assert_called_once()

    @patch("openviper.tasks.decorators.get_broker")
    @patch("openviper.tasks.decorators.dramatiq.actor")
    def test_decorator_zero_retries(self, mock_dramatiq_actor, mock_get_broker):
        """@task should allow max_retries=0 to disable retries."""
        mock_broker = MagicMock()
        mock_get_broker.return_value = mock_broker
        mock_actor_instance = MagicMock()
        mock_dramatiq_actor.return_value = mock_actor_instance

        @task(max_retries=0)
        def my_task():
            pass

        args, kwargs = mock_dramatiq_actor.call_args
        assert kwargs["max_retries"] == 0
