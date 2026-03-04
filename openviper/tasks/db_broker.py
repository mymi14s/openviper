"""Database-backed broker implementation for Dramatiq."""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from dramatiq.broker import Broker, Consumer, MessageProxy
from dramatiq.message import Message

from openviper.conf import settings
from openviper.utils import timezone

logger = logging.getLogger("openviper.tasks")

# Exponential back-off bounds for the consumer poll loop.
_POLL_MIN_SLEEP: float = 0.1  # 100 ms
_POLL_MAX_SLEEP: float = 2.0  # 2 000 ms


class DatabaseBroker(Broker):
    """A Dramatiq broker that stores messages in a database table."""

    def __init__(self, *, middleware: list | None = None):
        super().__init__(middleware=middleware)
        self._engine = self._get_sync_engine()
        self._supports_skip_locked = self._engine.dialect.name in ("postgresql", "mysql")
        self._metadata = sa.MetaData()
        self._table = sa.Table(
            "openviper_tasks",
            self._metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("queue_name", sa.String(100), nullable=False),
            sa.Column("message", sa.LargeBinary, nullable=False),
            sa.Column("status", sa.String(20), default="pending"),
            sa.Column("eta", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    def _get_sync_engine(self) -> sa.engine.Engine:
        url = settings.DATABASE_URL
        # Translate async-driver URLs to their synchronous equivalents.
        sync_url = url
        replacements = {
            "sqlite+aiosqlite://": "sqlite://",
            "postgresql+asyncpg://": "postgresql://",
            "mysql+aiomysql://": "mysql://",
        }
        for old, new in replacements.items():
            if sync_url.startswith(old):
                sync_url = new + sync_url[len(old) :]
                break

        kwargs: dict[str, Any] = {}
        if ":memory:" not in sync_url:
            # Pool configuration from TASKS settings (with safe defaults).
            task_cfg: dict[str, Any] = getattr(settings, "TASKS", {}) or {}
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = int(task_cfg.get("db_pool_size", 5))
            kwargs["max_overflow"] = int(task_cfg.get("db_max_overflow", 10))
            kwargs["pool_recycle"] = int(task_cfg.get("db_pool_recycle", 1800))

        return sa.create_engine(sync_url, **kwargs)

    def declare_queue(self, queue_name: str) -> None:
        """Declare a queue by adding it to the set of known queues."""
        self.queues[queue_name] = True

    def enqueue(self, message: Message, delay: int | None = None) -> Message:
        """Store the message in the database."""
        eta: datetime.datetime | None = None

        delay_ms = delay or message.options.get("delay")
        eta_ms = message.options.get("eta")

        if delay_ms:
            eta = timezone.now() + datetime.timedelta(milliseconds=delay_ms)
        elif eta_ms:
            eta = datetime.datetime.fromtimestamp(eta_ms / 1000.0)

        with self._engine.connect() as conn:
            conn.execute(
                self._table.insert().values(
                    queue_name=message.queue_name,
                    message=message.encode(),
                    status="pending",
                    eta=eta,
                )
            )
            conn.commit()
        logger.debug(
            "Enqueued message %s to queue %s (eta: %s)",
            message.message_id,
            message.queue_name,
            eta,
        )
        return message

    def consume(
        self, queue_name: str, prefetch: int = 1, timeout: int = 5000
    ) -> Iterable[MessageProxy | None]:
        return _DatabaseConsumer(self, queue_name, prefetch, timeout)

    def get_declared_queues(self) -> set[str]:
        return set(self.queues) or {"default"}


class _DatabaseConsumer(Consumer):
    def __init__(self, broker: DatabaseBroker, queue_name: str, prefetch: int, timeout: int):
        self.broker = broker
        self.queue_name = queue_name
        self.prefetch = prefetch
        self.timeout = timeout

    def __next__(self) -> MessageProxy | None:
        """Poll the database for the next pending message.

        Uses ``FOR UPDATE SKIP LOCKED`` on PostgreSQL and MySQL so that
        multiple workers can poll concurrently without delivering the same
        message twice.  Falls back to a plain ``SELECT`` on SQLite.

        Applies exponential back-off between empty polls (100 ms → 2 000 ms)
        to reduce database load during idle periods.
        """
        start_time = time.monotonic()
        sleep_time = _POLL_MIN_SLEEP

        while True:
            with self.broker._engine.begin() as conn:
                now = timezone.now()
                base_stmt = (
                    sa.select(self.broker._table.c.id, self.broker._table.c.message)
                    .where(
                        sa.and_(
                            self.broker._table.c.queue_name == self.queue_name,
                            self.broker._table.c.status == "pending",
                            sa.or_(
                                self.broker._table.c.eta.is_(None),
                                self.broker._table.c.eta <= now,
                            ),
                        )
                    )
                    .order_by(self.broker._table.c.created_at.asc())
                    .limit(1)
                )

                # SKIP LOCKED prevents multiple workers from picking the same row.
                if self.broker._supports_skip_locked:
                    base_stmt = base_stmt.with_for_update(skip_locked=True)

                row = conn.execute(base_stmt).fetchone()
                if row:
                    task_id, message_data = row
                    conn.execute(
                        self.broker._table.update()
                        .where(self.broker._table.c.id == task_id)
                        .values(status="processing")
                    )
                    message = Message.decode(message_data)
                    message = message.copy(options={"db_task_id": task_id})
                    logger.info(
                        "Found task %d for queue %s. Status -> processing.",
                        task_id,
                        self.queue_name,
                    )
                    return MessageProxy(message)

            # Check timeout.
            elapsed_ms = (time.monotonic() - start_time) * 1000
            if elapsed_ms >= self.timeout:
                return None

            # Exponential back-off: cap sleep to remaining timeout budget.
            remaining_s = (self.timeout / 1000) - (time.monotonic() - start_time)
            actual_sleep = min(sleep_time, max(remaining_s, 0.0))
            if actual_sleep > 0.0:
                time.sleep(actual_sleep)
            sleep_time = min(sleep_time * 2.0, _POLL_MAX_SLEEP)

    def ack(self, message: MessageProxy) -> None:
        """Mark the task as completed."""
        db_task_id = message.options.get("db_task_id")
        if db_task_id:
            with self.broker._engine.begin() as conn:
                conn.execute(
                    self.broker._table.update()
                    .where(self.broker._table.c.id == db_task_id)
                    .values(status="completed")
                )

    def nack(self, message: MessageProxy) -> None:
        """Mark the task as failed."""
        db_task_id = message.options.get("db_task_id")
        if db_task_id:
            with self.broker._engine.begin() as conn:
                conn.execute(
                    self.broker._table.update()
                    .where(self.broker._table.c.id == db_task_id)
                    .values(status="failed")
                )

    def requeue(self, messages: Iterable[MessageProxy]) -> None:
        """Mark the tasks as pending again."""
        db_task_ids = [m.options.get("db_task_id") for m in messages if m.options.get("db_task_id")]
        if db_task_ids:
            with self.broker._engine.begin() as conn:
                conn.execute(
                    self.broker._table.update()
                    .where(self.broker._table.c.id.in_(db_task_ids))
                    .values(status="pending")
                )
