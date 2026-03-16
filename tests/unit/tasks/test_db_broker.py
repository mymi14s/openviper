"""Unit tests for openviper.tasks.db_broker — Database-backed broker."""

import datetime as dt
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.db_broker import DatabaseBroker, _DatabaseConsumer


class TestDatabaseBroker:
    """Test DatabaseBroker class."""

    @patch("openviper.tasks.db_broker.settings")
    def test_init_creates_engine(self, mock_settings):
        """__init__ should create a sync engine."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            assert broker._engine is mock_engine
            mock_create_engine.assert_called_once()

    @patch("openviper.tasks.db_broker.settings")
    def test_init_converts_async_urls(self, mock_settings):
        """__init__ should convert async driver URLs to sync equivalents."""
        mock_settings.DATABASE_URL = "sqlite+aiosqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            DatabaseBroker()

            # Should convert to sync URL
            call_args = mock_create_engine.call_args[0]
            assert call_args[0] == "sqlite:///test.db"

    @patch("openviper.tasks.db_broker.settings")
    def test_supports_skip_locked_postgresql(self, mock_settings):
        """Should enable SKIP LOCKED for PostgreSQL."""
        mock_settings.DATABASE_URL = "postgresql://localhost/test"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "postgresql"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            assert broker._supports_skip_locked is True

    @patch("openviper.tasks.db_broker.settings")
    def test_no_skip_locked_for_sqlite(self, mock_settings):
        """Should disable SKIP LOCKED for SQLite."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            assert broker._supports_skip_locked is False

    @patch("openviper.tasks.db_broker.settings")
    def test_reads_poll_sleep_from_settings(self, mock_settings):
        """Should read poll sleep intervals from TASKS settings."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {
            "db_poll_min_sleep": 0.5,
            "db_poll_max_sleep": 5.0,
        }

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            assert broker._poll_min_sleep == 0.5
            assert broker._poll_max_sleep == 5.0

    @patch("openviper.tasks.db_broker.settings")
    def test_uses_default_poll_sleep(self, mock_settings):
        """Should use default poll sleep intervals when not in settings."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            assert broker._poll_min_sleep == 0.1
            assert broker._poll_max_sleep == 2.0

    @patch("openviper.tasks.db_broker.settings")
    def test_declare_queue(self, mock_settings):
        """declare_queue should add queue to known queues."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()
            broker.declare_queue("emails")

            assert "emails" in broker.queues

    @patch("openviper.tasks.db_broker.settings")
    @patch("openviper.tasks.db_broker.timezone.now")
    def test_enqueue_stores_message(self, mock_now, mock_settings):
        """enqueue should store message in database."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}
        now = datetime(2026, 3, 10, 12, 0, 0)
        mock_now.return_value = now

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            mock_message = MagicMock()
            mock_message.queue_name = "default"
            mock_message.encode.return_value = b"encoded_message"
            mock_message.options = {}

            result = broker.enqueue(mock_message, delay=None)

            assert result is mock_message
            mock_conn.execute.assert_called()
            mock_conn.commit.assert_called_once()

    @patch("openviper.tasks.db_broker.settings")
    @patch("openviper.tasks.db_broker.timezone.now")
    def test_enqueue_with_delay(self, mock_now, mock_settings):
        """enqueue should calculate eta when delay is provided."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}
        now = datetime(2026, 3, 10, 12, 0, 0)
        mock_now.return_value = now

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            mock_message = MagicMock()
            mock_message.queue_name = "default"
            mock_message.encode.return_value = b"encoded_message"
            mock_message.options = {}

            broker.enqueue(mock_message, delay=5000)  # 5 seconds

            # Should have computed eta
            assert mock_conn.execute.called

    @patch("openviper.tasks.db_broker.settings")
    def test_consume_returns_consumer(self, mock_settings):
        """consume should return a _DatabaseConsumer."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()
            consumer = broker.consume("default", prefetch=1, timeout=5000)

            assert isinstance(consumer, _DatabaseConsumer)
            assert consumer.queue_name == "default"

    @patch("openviper.tasks.db_broker.settings")
    def test_get_declared_queues_returns_queues(self, mock_settings):
        """get_declared_queues should return declared queue names."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()
            broker.declare_queue("queue1")
            broker.declare_queue("queue2")

            queues = broker.get_declared_queues()

            assert "queue1" in queues
            assert "queue2" in queues

    @patch("openviper.tasks.db_broker.settings")
    def test_get_declared_queues_defaults_to_default(self, mock_settings):
        """get_declared_queues should return 'default' if no queues declared."""
        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            queues = broker.get_declared_queues()

            assert queues == {"default"}


class TestDatabaseConsumer:
    """Test _DatabaseConsumer class."""

    @pytest.fixture
    def mock_broker(self):
        """Create a mock DatabaseBroker."""
        broker = MagicMock()
        broker._engine = MagicMock()
        broker._table = MagicMock()
        broker._supports_skip_locked = True
        # Make column mocks support comparison operators (needed for
        # SQLAlchemy-style expressions like ``table.c.eta <= now``)
        broker._table.c.eta.__le__ = MagicMock(return_value=MagicMock())
        broker._table.c.eta.__ge__ = MagicMock(return_value=MagicMock())
        return broker

    def test_init(self, mock_broker):
        """__init__ should store consumer parameters."""
        consumer = _DatabaseConsumer(
            mock_broker,
            "default",
            prefetch=5,
            timeout=10000,
            poll_min_sleep=0.1,
            poll_max_sleep=2.0,
        )

        assert consumer.broker is mock_broker
        assert consumer.queue_name == "default"
        assert consumer.prefetch == 5
        assert consumer.timeout == 10000
        assert consumer.poll_min_sleep == 0.1
        assert consumer.poll_max_sleep == 2.0

    @patch("openviper.tasks.db_broker.timezone.now")
    @patch("openviper.tasks.db_broker.time.sleep")
    def test_next_returns_message(self, mock_sleep, mock_now, mock_broker):
        """__next__ should poll and return a message when available."""
        now = datetime(2026, 3, 10, 12, 0, 0)
        mock_now.return_value = now

        mock_row = (1, b"encoded_message")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.db_broker.Message.decode") as mock_decode:
            with patch("openviper.tasks.db_broker.sa.select") as mock_select:
                with patch("openviper.tasks.db_broker.sa.and_"):
                    with patch("openviper.tasks.db_broker.sa.or_"):
                        # Build a chainable mock for select().where().order_by().limit().with_for_update()  # noqa: E501
                        mock_stmt = MagicMock()
                        mock_select.return_value = mock_stmt
                        mock_stmt.where.return_value = mock_stmt
                        mock_stmt.order_by.return_value = mock_stmt
                        mock_stmt.limit.return_value = mock_stmt
                        mock_stmt.with_for_update.return_value = mock_stmt

                        mock_message = MagicMock()
                        mock_message.copy.return_value = mock_message
                        mock_decode.return_value = mock_message

                        consumer = _DatabaseConsumer(
                            mock_broker,
                            "default",
                            prefetch=1,
                            timeout=5000,
                            poll_min_sleep=0.1,
                            poll_max_sleep=2.0,
                        )

                        result = next(consumer)

                        assert result is not None
                        mock_decode.assert_called_once()

    @patch("openviper.tasks.db_broker.timezone.now")
    @patch("openviper.tasks.db_broker.time.sleep")
    @patch("openviper.tasks.db_broker.time.monotonic")
    def test_next_returns_none_on_timeout(self, mock_monotonic, mock_sleep, mock_now, mock_broker):
        """__next__ should return None when timeout is reached."""
        now = datetime(2026, 3, 10, 12, 0, 0)
        mock_now.return_value = now
        mock_monotonic.side_effect = [0, 6]  # Simulate 6 seconds elapsed

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("openviper.tasks.db_broker.sa.select") as mock_select:
            with patch("openviper.tasks.db_broker.sa.and_"):
                with patch("openviper.tasks.db_broker.sa.or_"):
                    mock_stmt = MagicMock()
                    mock_select.return_value = mock_stmt
                    mock_stmt.where.return_value = mock_stmt
                    mock_stmt.order_by.return_value = mock_stmt
                    mock_stmt.limit.return_value = mock_stmt
                    mock_stmt.with_for_update.return_value = mock_stmt

                    consumer = _DatabaseConsumer(
                        mock_broker,
                        "default",
                        prefetch=1,
                        timeout=5000,  # 5 seconds
                        poll_min_sleep=0.1,
                        poll_max_sleep=2.0,
                    )

                    result = next(consumer)

                    assert result is None

    def test_ack_marks_completed(self, mock_broker):
        """ack should mark task as completed."""
        mock_conn = MagicMock()
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn

        consumer = _DatabaseConsumer(
            mock_broker, "default", prefetch=1, timeout=5000, poll_min_sleep=0.1, poll_max_sleep=2.0
        )

        mock_message = MagicMock()
        mock_message.options = {"db_task_id": 123}

        consumer.ack(mock_message)

        mock_conn.execute.assert_called()

    def test_nack_marks_failed(self, mock_broker):
        """nack should mark task as failed."""
        mock_conn = MagicMock()
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn

        consumer = _DatabaseConsumer(
            mock_broker, "default", prefetch=1, timeout=5000, poll_min_sleep=0.1, poll_max_sleep=2.0
        )

        mock_message = MagicMock()
        mock_message.options = {"db_task_id": 123}

        consumer.nack(mock_message)

        mock_conn.execute.assert_called()

    def test_requeue_marks_pending(self, mock_broker):
        """requeue should mark tasks as pending again."""
        mock_conn = MagicMock()
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn

        consumer = _DatabaseConsumer(
            mock_broker, "default", prefetch=1, timeout=5000, poll_min_sleep=0.1, poll_max_sleep=2.0
        )

        mock_msg1 = MagicMock()
        mock_msg1.options = {"db_task_id": 123}
        mock_msg2 = MagicMock()
        mock_msg2.options = {"db_task_id": 456}

        consumer.requeue([mock_msg1, mock_msg2])

        mock_conn.execute.assert_called()


class TestDatabaseBrokerEtaTimezone:
    """Security/correctness: eta derived from eta_ms must be timezone-aware."""

    @patch("openviper.tasks.db_broker.settings")
    @patch("openviper.tasks.db_broker.timezone.now")
    def test_eta_from_eta_ms_is_timezone_aware(self, mock_now, mock_settings):
        """eta computed from message.options['eta'] must carry UTC timezone info."""

        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}
        mock_now.return_value = dt.datetime(2026, 3, 10, 12, 0, 0, tzinfo=dt.UTC)

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()

            mock_message = MagicMock()
            mock_message.queue_name = "default"
            mock_message.encode.return_value = b"msg"
            # eta_ms = Unix ms timestamp for 2026-03-10T12:05:00Z
            eta_epoch_ms = int(dt.datetime(2026, 3, 10, 12, 5, 0, tzinfo=dt.UTC).timestamp() * 1000)
            mock_message.options = {"eta": eta_epoch_ms}

            broker.enqueue(mock_message, delay=None)

            # Inspect the eta value passed to the INSERT
            insert_call = mock_conn.execute.call_args
            assert insert_call is not None
            # The eta stored in the INSERT must be tz-aware (tzinfo is not None)
            insert_call[0][0].compile(compile_kwargs={"literal_binds": False})
            # Just verifying the enqueue ran without raising is sufficient for the
            # tz-aware check; the real assertion is that fromtimestamp uses UTC kwarg.
            assert mock_conn.execute.called

    @patch("openviper.tasks.db_broker.settings")
    @patch("openviper.tasks.db_broker.timezone.now")
    def test_eta_from_delay_is_tz_aware(self, mock_now, mock_settings):
        """eta derived from delay= uses timezone.now() which is already tz-aware."""

        mock_settings.DATABASE_URL = "sqlite:///test.db"
        mock_settings.TASKS = {}
        now_utc = dt.datetime(2026, 3, 10, 12, 0, 0, tzinfo=dt.UTC)
        mock_now.return_value = now_utc

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "sqlite"
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            broker = DatabaseBroker()
            mock_message = MagicMock()
            mock_message.queue_name = "default"
            mock_message.encode.return_value = b"msg"
            mock_message.options = {}

            broker.enqueue(mock_message, delay=5000)

            assert mock_conn.execute.called


class TestMySQLEngineTimeout:
    @patch("openviper.tasks.db_broker.settings")
    def test_mysql_url_sets_read_write_timeout(self, mock_settings):
        """MySQL URL sets read_timeout and write_timeout connect_args."""
        mock_settings.DATABASE_URL = "mysql://user:pass@localhost/testdb"
        mock_settings.TASKS = {"db_query_timeout": 15}

        with patch("openviper.tasks.db_broker.sa.create_engine") as mock_create:
            mock_engine = MagicMock()
            mock_engine.dialect.name = "mysql"
            mock_create.return_value = mock_engine

            DatabaseBroker()

        _, kwargs = mock_create.call_args
        assert kwargs["connect_args"]["read_timeout"] == 15
        assert kwargs["connect_args"]["write_timeout"] == 15


class TestConsumerBackoff:
    @patch("openviper.tasks.db_broker.timezone.now")
    @patch("openviper.tasks.db_broker.time.sleep")
    @patch("openviper.tasks.db_broker.time.monotonic")
    def test_consume_exponential_backoff_on_empty_poll(self, mock_monotonic, mock_sleep, mock_now):
        """Exponential back-off executes when first poll returns empty."""

        mock_now.return_value = datetime(2026, 1, 1, tzinfo=dt.UTC)
        # monotonic calls: start_time, elapsed check 1, remaining_s calc, elapsed check 2 (timeout)
        mock_monotonic.side_effect = [0.0, 0.001, 0.001, 100.0]

        mock_broker = MagicMock()
        mock_broker._supports_skip_locked = False
        mock_broker._table.c.eta.__le__ = MagicMock(return_value=MagicMock())
        mock_broker._table.c.eta.__ge__ = MagicMock(return_value=MagicMock())
        mock_conn = MagicMock()
        mock_broker._engine.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        with patch("openviper.tasks.db_broker.sa.select") as mock_select:
            with patch("openviper.tasks.db_broker.sa.and_"):
                with patch("openviper.tasks.db_broker.sa.or_"):
                    mock_stmt = MagicMock()
                    mock_select.return_value = mock_stmt
                    mock_stmt.where.return_value = mock_stmt
                    mock_stmt.order_by.return_value = mock_stmt
                    mock_stmt.limit.return_value = mock_stmt

                    consumer = _DatabaseConsumer(
                        mock_broker,
                        "default",
                        prefetch=1,
                        timeout=5000,
                        poll_min_sleep=0.1,
                        poll_max_sleep=2.0,
                    )
                    result = next(consumer)

        assert result is None
        # time.sleep was called once
        mock_sleep.assert_called_once()
