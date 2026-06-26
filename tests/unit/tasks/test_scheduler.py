"""Tests for openviper.tasks.scheduler - cron and interval scheduling."""

from __future__ import annotations

import datetime
import time
from unittest.mock import MagicMock, patch

import pytest

from openviper.tasks.decorators import actor
from openviper.tasks.periodic import periodic
from openviper.tasks.registry import Registry
from openviper.tasks.scheduler import Scheduler, compute_next_cron_fire


class TestComputeNextCronFire:
    """Test the cron expression fire-time calculator."""

    def test_compute_next_cron_fire_with_croniter(self) -> None:
        """When croniter is available, compute the next fire time correctly."""
        base = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
        result = compute_next_cron_fire("0 * * * *", base)
        assert result > base

    def test_compute_next_cron_fire_fallback_without_croniter(self) -> None:
        """When croniter is unavailable, fall back to minute-aligned approximation."""
        base = datetime.datetime(2025, 1, 1, 0, 0, 30, tzinfo=datetime.UTC)
        with patch.dict("sys.modules", {"croniter": None}):
            result = compute_next_cron_fire("0 * * * *", base)
            assert result > base


class TestScheduler:
    """Test the Scheduler background thread."""

    def setup_method(self) -> None:
        Registry().clear()

    def test_scheduler_start_creates_thread(self) -> None:
        """Starting the scheduler should create a daemon thread."""
        scheduler = Scheduler()
        scheduler.start()
        try:
            assert scheduler.thread is not None
            assert scheduler.thread.daemon is True
            assert scheduler.thread.name == "openviper-scheduler"
        finally:
            scheduler.stop()

    def test_scheduler_stop_clears_thread(self) -> None:
        """Stopping the scheduler should clear the thread reference."""
        scheduler = Scheduler()
        scheduler.start()
        scheduler.stop()
        assert scheduler.thread is None

    def test_scheduler_start_idempotent(self) -> None:
        """Starting an already-running scheduler should be a no-op."""
        scheduler = Scheduler()
        scheduler.start()
        first_thread = scheduler.thread
        scheduler.start()
        assert scheduler.thread is first_thread
        scheduler.stop()

    @patch("openviper.tasks.scheduler.enqueue_task")
    def test_scheduler_fires_startup_jobs(self, mock_enqueue: MagicMock) -> None:
        """Startup jobs should be enqueued immediately on scheduler start."""
        @periodic(every="60s", startup=True)
        async def startup_task() -> None:
            pass

        scheduler = Scheduler()
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop()

        assert mock_enqueue.called

    @patch("openviper.tasks.scheduler.enqueue_task")
    def test_scheduler_skips_jobs_without_every(self, mock_enqueue: MagicMock) -> None:
        """Jobs with only cron (no every) should still be evaluated."""
        @periodic(cron="0 8 * * *")
        async def cron_only_task() -> None:
            pass

        scheduler = Scheduler()
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop()
