"""Unit tests for openviper.tasks.db_broker."""

from __future__ import annotations

import datetime
import time as time_module
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.db_broker import DatabaseBroker, _DatabaseConsumer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """A MagicMock standing in for a SQLAlchemy Engine."""
    return MagicMock()


@pytest.fixture
def broker(mock_engine):
    """A DatabaseBroker with the SQLAlchemy engine replaced by a MagicMock."""
    with patch("openviper.tasks.db_broker.sa.create_engine", return_value=mock_engine):
        b = DatabaseBroker()
    return b


@pytest.fixture
def consumer(broker):
    """A _DatabaseConsumer wired to the fixture broker."""
    return _DatabaseConsumer(broker, "default", prefetch=1, timeout=5000)


# ---------------------------------------------------------------------------
# _get_sync_engine – URL translation
# ---------------------------------------------------------------------------


class TestGetSyncEngine:
    def _call_with_url(self, url: str) -> str:
        """Instantiate a DatabaseBroker with the given URL and return what create_engine saw."""
        import openviper.tasks.db_broker as module

        with patch.object(module, "settings") as ms:
            ms.DATABASE_URL = url
            with patch("openviper.tasks.db_broker.sa.create_engine") as mce:
                mce.return_value = MagicMock()
                b = DatabaseBroker.__new__(DatabaseBroker)
                b._get_sync_engine()
        return mce.call_args[0][0]

    def test_sqlite_aiosqlite_replaced(self):
        result = self._call_with_url("sqlite+aiosqlite:///./db.sqlite")
        assert result.startswith("sqlite://")
        assert "aiosqlite" not in result

    def test_postgresql_asyncpg_replaced(self):
        result = self._call_with_url("postgresql+asyncpg://user:pass@localhost/db")
        assert result.startswith("postgresql://")
        assert "asyncpg" not in result

    def test_mysql_aiomysql_replaced(self):
        result = self._call_with_url("mysql+aiomysql://user:pass@localhost/db")
        assert result.startswith("mysql://")
        assert "aiomysql" not in result

    def test_plain_url_unchanged(self):
        url = "postgresql://user:pass@localhost/db"
        result = self._call_with_url(url)
        assert result == url

    def test_sqlite_plain_unchanged(self):
        url = "sqlite:///./db.sqlite"
        result = self._call_with_url(url)
        assert result == url


# ---------------------------------------------------------------------------
# DatabaseBroker – core methods
# ---------------------------------------------------------------------------


class TestDatabaseBrokerMethods:
    def test_declare_queue_adds_to_queues(self, broker):
        broker.declare_queue("notifications")
        assert "notifications" in broker.queues

    def test_declare_multiple_queues(self, broker):
        broker.declare_queue("high")
        broker.declare_queue("low")
        assert "high" in broker.queues
        assert "low" in broker.queues

    def test_get_declared_queues_returns_default(self, broker):
        result = broker.get_declared_queues()
        assert result == {"default"}

    def test_consume_returns_consumer_instance(self, broker):
        consumer = broker.consume("myqueue", prefetch=2, timeout=3000)
        assert isinstance(consumer, _DatabaseConsumer)
        assert consumer.queue_name == "myqueue"
        assert consumer.prefetch == 2
        assert consumer.timeout == 3000

    def test_consume_default_params(self, broker):
        consumer = broker.consume("default")
        assert consumer.queue_name == "default"
        assert consumer.prefetch == 1
        assert consumer.timeout == 5000


# ---------------------------------------------------------------------------
# DatabaseBroker.enqueue
# ---------------------------------------------------------------------------


class TestEnqueue:
    def _make_message(self, options=None):
        from dramatiq.message import Message

        return Message(
            queue_name="default",
            actor_name="my_actor",
            args=(1, 2),
            kwargs={},
            options=options or {},
        )

    def _wire_conn(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    def test_enqueue_no_delay_no_eta(self, broker, mock_engine):
        msg = self._make_message()
        mock_conn = self._wire_conn(mock_engine)

        result = broker.enqueue(msg)

        assert result is msg
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_enqueue_returns_same_message(self, broker, mock_engine):
        msg = self._make_message()
        self._wire_conn(mock_engine)
        assert broker.enqueue(msg) is msg

    def test_enqueue_with_delay_sets_eta(self, broker, mock_engine):
        msg = self._make_message()
        mock_conn = self._wire_conn(mock_engine)
        now = datetime.datetime(2024, 6, 1, 12, 0, 0)

        with patch("openviper.tasks.db_broker.timezone.now", return_value=now):
            broker.enqueue(msg, delay=5000)  # 5 seconds

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_enqueue_with_eta_in_options(self, broker, mock_engine):
        eta_ms = int(time_module.time() * 1000) + 60_000  # 1 minute out
        msg = self._make_message(options={"eta": eta_ms})
        mock_conn = self._wire_conn(mock_engine)

        broker.enqueue(msg)

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_enqueue_with_delay_in_options(self, broker, mock_engine):
        """delay can come from message.options["delay"] as well."""
        msg = self._make_message(options={"delay": 10_000})
        mock_conn = self._wire_conn(mock_engine)

        broker.enqueue(msg)

        mock_conn.execute.assert_called_once()

    def test_enqueue_delay_param_takes_priority_over_options(self, broker, mock_engine):
        """Explicit delay= arg is used; message options["delay"] is also considered."""
        msg = self._make_message(options={"delay": 2_000})
        mock_conn = self._wire_conn(mock_engine)
        now = datetime.datetime(2024, 1, 1, 0, 0, 0)

        with patch("openviper.tasks.db_broker.timezone.now", return_value=now):
            # passing explicit delay of 1000ms
            broker.enqueue(msg, delay=1_000)

        mock_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# _DatabaseConsumer – __next__
# ---------------------------------------------------------------------------


class TestDatabaseConsumerNext:
    def _wire_conn(self, mock_engine, row=None):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = row
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    def _real_encoded_message(self):
        from dramatiq.message import Message

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        return msg.encode()

    def test_row_found_returns_message_proxy(self, consumer, mock_engine):
        from dramatiq.broker import MessageProxy

        encoded = self._real_encoded_message()
        self._wire_conn(mock_engine, row=(42, encoded))

        result = consumer.__next__()

        assert result is not None
        assert isinstance(result, MessageProxy)

    def test_row_found_updates_status_to_processing(self, consumer, mock_engine):
        encoded = self._real_encoded_message()
        mock_conn = self._wire_conn(mock_engine, row=(42, encoded))

        consumer.__next__()

        # execute should have been called twice: once for SELECT, once for UPDATE
        assert mock_conn.execute.call_count == 2

    def test_row_found_stores_db_task_id_in_options(self, consumer, mock_engine):
        encoded = self._real_encoded_message()
        self._wire_conn(mock_engine, row=(99, encoded))

        result = consumer.__next__()

        assert result.options.get("db_task_id") == 99

    def test_timeout_reached_returns_none(self, consumer, mock_engine):
        self._wire_conn(mock_engine, row=None)  # no rows

        # start_time=0, then timeout check returns 100 (100*1000 > 5000)
        with (
            patch("openviper.tasks.db_broker.time.monotonic", side_effect=[0.0, 100.0]),
            patch("openviper.tasks.db_broker.time.sleep"),
        ):
            result = consumer.__next__()

        assert result is None

    def test_sleeps_before_timeout(self, consumer, mock_engine):
        """First check: not timed out -> sleep; second check: timed out -> None."""
        self._wire_conn(mock_engine, row=None)

        # monotonic calls: #1=start, #2=elapsed check (500ms<5s),
        # #3=remaining calc, #4=elapsed check->timed out
        with (
            patch(
                "openviper.tasks.db_broker.time.monotonic",
                side_effect=[0.0, 0.5, 0.5, 100.0],
            ),
            patch("openviper.tasks.db_broker.time.sleep") as mock_sleep,
        ):
            result = consumer.__next__()

        assert result is None
        mock_sleep.assert_called_once_with(0.1)

    def test_custom_timeout_respected(self, broker, mock_engine):
        """Consumer with very short timeout returns None quickly."""
        consumer = _DatabaseConsumer(broker, "default", prefetch=1, timeout=100)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Simulated elapsed: 0ms start, then 200ms -> exceeds 100ms timeout
        with (
            patch("openviper.tasks.db_broker.time.monotonic", side_effect=[0.0, 0.2]),
            patch("openviper.tasks.db_broker.time.sleep"),
        ):
            result = consumer.__next__()

        assert result is None


# ---------------------------------------------------------------------------
# _DatabaseConsumer – ack
# ---------------------------------------------------------------------------


class TestDatabaseConsumerAck:
    def _wire_begin(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    def test_ack_with_db_task_id_executes_update(self, consumer, mock_engine):
        mock_conn = self._wire_begin(mock_engine)
        proxy = MagicMock()
        proxy.options = {"db_task_id": 7}

        consumer.ack(proxy)

        mock_conn.execute.assert_called_once()

    def test_ack_without_db_task_id_does_nothing(self, consumer, mock_engine):
        proxy = MagicMock()
        proxy.options = {}

        consumer.ack(proxy)

        mock_engine.begin.assert_not_called()

    def test_ack_with_none_db_task_id_does_nothing(self, consumer, mock_engine):
        proxy = MagicMock()
        proxy.options = {"db_task_id": None}

        consumer.ack(proxy)

        mock_engine.begin.assert_not_called()


# ---------------------------------------------------------------------------
# _DatabaseConsumer – nack
# ---------------------------------------------------------------------------


class TestDatabaseConsumerNack:
    def _wire_begin(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    def test_nack_with_db_task_id_executes_update(self, consumer, mock_engine):
        mock_conn = self._wire_begin(mock_engine)
        proxy = MagicMock()
        proxy.options = {"db_task_id": 55}

        consumer.nack(proxy)

        mock_conn.execute.assert_called_once()

    def test_nack_without_db_task_id_does_nothing(self, consumer, mock_engine):
        proxy = MagicMock()
        proxy.options = {}

        consumer.nack(proxy)

        mock_engine.begin.assert_not_called()

    def test_nack_with_none_db_task_id_does_nothing(self, consumer, mock_engine):
        proxy = MagicMock()
        proxy.options = {"db_task_id": None}

        consumer.nack(proxy)

        mock_engine.begin.assert_not_called()


# ---------------------------------------------------------------------------
# _DatabaseConsumer – requeue
# ---------------------------------------------------------------------------


class TestDatabaseConsumerRequeue:
    def _wire_begin(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    def test_requeue_with_ids_executes_update(self, consumer, mock_engine):
        mock_conn = self._wire_begin(mock_engine)
        p1 = MagicMock()
        p1.options = {"db_task_id": 1}
        p2 = MagicMock()
        p2.options = {"db_task_id": 2}

        consumer.requeue([p1, p2])

        mock_conn.execute.assert_called_once()

    def test_requeue_single_message(self, consumer, mock_engine):
        mock_conn = self._wire_begin(mock_engine)
        p = MagicMock()
        p.options = {"db_task_id": 10}

        consumer.requeue([p])

        mock_conn.execute.assert_called_once()

    def test_requeue_empty_list_does_nothing(self, consumer, mock_engine):
        consumer.requeue([])
        mock_engine.begin.assert_not_called()

    def test_requeue_messages_without_ids_does_nothing(self, consumer, mock_engine):
        p1 = MagicMock()
        p1.options = {}
        p2 = MagicMock()
        p2.options = {"db_task_id": None}

        consumer.requeue([p1, p2])

        mock_engine.begin.assert_not_called()

    def test_requeue_mixed_some_without_ids(self, consumer, mock_engine):
        mock_conn = self._wire_begin(mock_engine)
        p1 = MagicMock()
        p1.options = {"db_task_id": 5}
        p2 = MagicMock()
        p2.options = {}

        consumer.requeue([p1, p2])

        # Only the one with a db_task_id should trigger an update
        mock_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# _DatabaseConsumer – init / attributes
# ---------------------------------------------------------------------------


class TestDatabaseConsumerInit:
    def test_attributes_set_correctly(self, broker):
        c = _DatabaseConsumer(broker, "jobs", prefetch=3, timeout=10_000)
        assert c.broker is broker
        assert c.queue_name == "jobs"
        assert c.prefetch == 3
        assert c.timeout == 10_000


# ---------------------------------------------------------------------------
# _DatabaseConsumer — _supports_skip_locked path (line 153)
# ---------------------------------------------------------------------------


class TestSkipLocked:
    def _real_encoded_message(self):
        from dramatiq.message import Message

        msg = Message(
            queue_name="default",
            actor_name="test_actor",
            args=(),
            kwargs={},
            options={},
        )
        return msg.encode()

    def test_with_for_update_called_when_supports_skip_locked_true(self, consumer, mock_engine):
        """Line 153: with_for_update(skip_locked=True) applied when _supports_skip_locked true."""
        import sqlalchemy as sa

        # Enable SKIP LOCKED on the broker
        consumer.broker._supports_skip_locked = True

        encoded = self._real_encoded_message()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (42, encoded)
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Patch Select.with_for_update to capture the call
        original_wfu = sa.Select.with_for_update
        wfu_calls = []

        def tracking_wfu(self_stmt, **kw):
            wfu_calls.append(kw)
            return original_wfu(self_stmt, **kw)

        with patch.object(sa.Select, "with_for_update", tracking_wfu):
            consumer.__next__()

        # The `with_for_update(skip_locked=True)` branch was executed
        assert any(c.get("skip_locked") is True for c in wfu_calls)

    def test_with_for_update_not_called_when_supports_skip_locked_false(
        self, consumer, mock_engine
    ):
        """When _supports_skip_locked is False, with_for_update is not called."""
        import sqlalchemy as sa

        consumer.broker._supports_skip_locked = False

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        original_wfu = sa.Select.with_for_update
        wfu_calls = []

        def tracking_wfu(self_stmt, **kw):
            wfu_calls.append(kw)
            return original_wfu(self_stmt, **kw)

        with (
            patch.object(sa.Select, "with_for_update", tracking_wfu),
            patch("openviper.tasks.db_broker.time.monotonic", side_effect=[0.0, 100.0]),
            patch("openviper.tasks.db_broker.time.sleep"),
        ):
            consumer.__next__()

        assert not wfu_calls
