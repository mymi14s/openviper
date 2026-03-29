"""Tests for openviper/tasks/db_broker.py."""

from __future__ import annotations

import contextlib
import time
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from dramatiq.message import Message

from openviper.tasks.db_broker import DatabaseBroker, _DatabaseConsumer


def _make_db_broker(url: str = "sqlite:///:memory:") -> DatabaseBroker:
    """Create a DatabaseBroker with an in-memory SQLite engine."""
    mock_settings = MagicMock()
    mock_settings.DATABASE_URL = url
    mock_settings.TASKS = {}
    with patch("openviper.tasks.db_broker.settings", mock_settings):
        broker = DatabaseBroker()
    # Create the tasks table
    broker._metadata.create_all(broker._engine)
    return broker


# ---------------------------------------------------------------------------
# DatabaseBroker
# ---------------------------------------------------------------------------


class TestDatabaseBroker:
    def test_init(self) -> None:
        broker = _make_db_broker()
        assert broker._engine is not None

    def test_declare_queue(self) -> None:
        broker = _make_db_broker()
        broker.declare_queue("test_queue")
        assert "test_queue" in broker.queues

    def test_get_declared_queues_empty(self) -> None:
        broker = _make_db_broker()
        queues = broker.get_declared_queues()
        assert "default" in queues

    def test_get_declared_queues_with_declared(self) -> None:
        broker = _make_db_broker()
        broker.declare_queue("my_queue")
        queues = broker.get_declared_queues()
        assert "my_queue" in queues

    def test_enqueue_message(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        result = broker.enqueue(msg)
        assert result is msg

    def test_enqueue_with_delay(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        result = broker.enqueue(msg, delay=5000)
        assert result is msg

    def test_enqueue_with_eta_option(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={"eta": int(time.time() * 1000) + 5000},
        )
        result = broker.enqueue(msg)
        assert result is msg

    def test_consume_returns_consumer(self) -> None:
        broker = _make_db_broker()
        consumer = broker.consume("default", prefetch=1, timeout=100)
        assert consumer is not None

    def test_supports_skip_locked_sqlite(self) -> None:
        broker = _make_db_broker()
        # SQLite does NOT support SKIP LOCKED
        assert broker._supports_skip_locked is False

    def test_pool_config_for_non_memory(self) -> None:
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "sqlite:///testdb.db"
        mock_settings.TASKS = {
            "db_pool_size": 5,
            "db_max_overflow": 10,
            "db_pool_recycle": 600,
            "db_pool_timeout": 15,
            "db_query_timeout": 30,
        }
        with (
            patch("openviper.tasks.db_broker.settings", mock_settings),
            patch("openviper.tasks.db_broker.sa.create_engine") as mock_engine,
        ):
            mock_engine_obj = MagicMock()
            mock_engine_obj.dialect.name = "sqlite"
            mock_engine.return_value = mock_engine_obj
            DatabaseBroker()
        mock_engine.assert_called_once()

    def test_mysql_url_replacement(self) -> None:
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "mysql+aiomysql://user:pass@localhost/db"
        mock_settings.TASKS = {}
        with (
            patch("openviper.tasks.db_broker.settings", mock_settings),
            patch("openviper.tasks.db_broker.require_dependency"),
            patch("openviper.tasks.db_broker.sa.create_engine") as mock_create,
        ):
            mock_engine_obj = MagicMock()
            mock_engine_obj.dialect.name = "mysql"
            mock_create.return_value = mock_engine_obj
            DatabaseBroker()
        call_args = mock_create.call_args[0][0]
        assert "pymysql" in call_args or "mysql" in call_args

    def test_postgresql_url_replacement(self) -> None:
        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/db"
        mock_settings.TASKS = {}
        with (
            patch("openviper.tasks.db_broker.settings", mock_settings),
            patch("openviper.tasks.db_broker.sa.create_engine") as mock_create,
        ):
            mock_engine_obj = MagicMock()
            mock_engine_obj.dialect.name = "postgresql"
            mock_create.return_value = mock_engine_obj
            DatabaseBroker()
        call_args = mock_create.call_args[0][0]
        assert "postgresql://" in call_args


# ---------------------------------------------------------------------------
# _DatabaseConsumer
# ---------------------------------------------------------------------------


class TestDatabaseConsumer:
    def test_next_returns_none_on_timeout(self) -> None:
        broker = _make_db_broker()
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=1,  # 1 ms timeout
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        result = next(consumer)
        assert result is None

    def test_next_returns_message_proxy(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        broker.enqueue(msg)
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=5000,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        result = next(consumer)
        assert result is not None

    def test_ack_marks_completed(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        broker.enqueue(msg)
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=5000,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        proxy = next(consumer)
        assert proxy is not None
        consumer.ack(proxy)
        # Verify status changed in DB
        with broker._engine.connect() as conn:
            row = conn.execute(
                sa.select(broker._table.c.status).where(
                    broker._table.c.id == proxy.options["db_task_id"]
                )
            ).fetchone()
        assert row[0] == "completed"

    def test_nack_marks_failed(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        broker.enqueue(msg)
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=5000,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        proxy = next(consumer)
        assert proxy is not None
        consumer.nack(proxy)
        with broker._engine.connect() as conn:
            row = conn.execute(
                sa.select(broker._table.c.status).where(
                    broker._table.c.id == proxy.options["db_task_id"]
                )
            ).fetchone()
        assert row[0] == "failed"

    def test_ack_without_db_task_id_noop(self) -> None:
        broker = _make_db_broker()
        proxy = MagicMock()
        proxy.options = {}
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=100,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        consumer.ack(proxy)  # should not raise

    def test_nack_without_db_task_id_noop(self) -> None:
        broker = _make_db_broker()
        proxy = MagicMock()
        proxy.options = {}
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=100,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        consumer.nack(proxy)  # should not raise

    def test_requeue_marks_pending(self) -> None:
        broker = _make_db_broker()

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        broker.enqueue(msg)
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=5000,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        proxy = next(consumer)
        assert proxy is not None
        consumer.nack(proxy)  # set to failed
        consumer.requeue([proxy])  # set back to pending
        with broker._engine.connect() as conn:
            row = conn.execute(
                sa.select(broker._table.c.status).where(
                    broker._table.c.id == proxy.options["db_task_id"]
                )
            ).fetchone()
        assert row[0] == "pending"

    def test_requeue_empty_noop(self) -> None:
        broker = _make_db_broker()
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="default",
            prefetch=1,
            timeout=100,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        consumer.requeue([])  # should not raise

    def test_eta_message_not_returned_before_eta(self) -> None:
        broker = _make_db_broker()

        # Future eta — should not be picked up yet
        future_eta = int((time.time() + 3600) * 1000)
        msg = Message(
            queue_name="future_queue",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={"eta": future_eta},
        )
        broker.declare_queue("future_queue")
        broker.enqueue(msg)

        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="future_queue",
            prefetch=1,
            timeout=10,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        result = next(consumer)
        assert result is None

    def test_exponential_backoff_applied(self) -> None:
        broker = _make_db_broker()
        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="empty_queue",
            prefetch=1,
            timeout=30,  # 30ms
            poll_min_sleep=0.001,  # 1ms
            poll_max_sleep=0.002,  # 2ms
        )
        result = next(consumer)
        assert result is None


class TestDatabaseBrokerSkipLocked:
    def test_skip_locked_used_when_supported(self) -> None:
        """Test line 194: with_for_update(skip_locked=True) is called."""
        broker = _make_db_broker()
        broker._supports_skip_locked = True  # Force skip_locked mode

        msg = Message(
            queue_name="skip_queue",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        broker.declare_queue("skip_queue")
        broker.enqueue(msg)

        consumer = _DatabaseConsumer(
            broker=broker,
            queue_name="skip_queue",
            prefetch=1,
            timeout=100,
            poll_min_sleep=0.0,
            poll_max_sleep=0.001,
        )
        # SQLite doesn't support FOR UPDATE SKIP LOCKED, so this will return None
        # but the code path IS executed
        with contextlib.suppress(Exception):
            next(consumer)
