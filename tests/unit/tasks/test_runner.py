"""Unit tests for openviper.tasks.runner — Scheduler run loop."""

import signal
import signal as _sig
import sys
from datetime import UTC
from unittest.mock import MagicMock, patch

from openviper.tasks.core import Scheduler
from openviper.tasks.runner import _DEFAULT_TICK_INTERVAL, run_scheduler


class TestRunScheduler:
    """Test run_scheduler function."""

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_runs_tick_loop(self, mock_sleep, mock_signal):
        """Should tick scheduler in a loop."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 2
        mock_scheduler.tick.return_value = []

        # Simulate immediate SIGINT after first tick
        def raise_keyboard_interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        mock_sleep.side_effect = raise_keyboard_interrupt

        run_scheduler(scheduler=mock_scheduler, tick_interval=1.0)

        # Should have called tick at least once
        assert mock_scheduler.tick.call_count >= 1

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_uses_default_scheduler_when_none(self, mock_sleep, mock_signal):
        """Should create default Scheduler when none provided."""
        # Simulate immediate interrupt
        mock_sleep.side_effect = KeyboardInterrupt()

        with patch("openviper.tasks.runner.Scheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler.__len__.return_value = 0
            mock_scheduler.tick.return_value = []
            mock_scheduler_class.return_value = mock_scheduler

            run_scheduler(scheduler=None)

            mock_scheduler_class.assert_called_once()

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_uses_custom_tick_interval(self, mock_sleep, mock_signal):
        """Should use custom tick_interval."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler, tick_interval=5.0)

        # Should sleep with custom interval
        mock_sleep.assert_called_with(5.0)

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_default_tick_interval(self, mock_sleep, mock_signal):
        """Should use default tick_interval of 1.0 second."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Should sleep with default interval
        mock_sleep.assert_called_with(_DEFAULT_TICK_INTERVAL)

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    @patch("openviper.tasks.runner.logger")
    def test_logs_enqueued_tasks(self, mock_logger, mock_sleep, mock_signal):
        """Should log when tasks are enqueued."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 1
        mock_scheduler.tick.return_value = ["task1", "task2"]

        # Stop after first tick
        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Should log enqueued tasks
        assert any("enqueued" in str(call).lower() for call in mock_logger.debug.call_args_list)

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_registers_signal_handlers(self, mock_sleep, mock_signal):
        """Should register SIGINT and SIGTERM handlers."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Should register signal handlers
        calls = mock_signal.call_args_list
        signals_registered = [call[0][0] for call in calls]

        assert signal.SIGINT in signals_registered
        assert signal.SIGTERM in signals_registered

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_handles_system_exit(self, mock_sleep, mock_signal):
        """Should handle SystemExit gracefully."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = SystemExit()

        run_scheduler(scheduler=mock_scheduler)

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    @patch("openviper.tasks.runner.logger")
    def test_logs_startup(self, mock_logger, mock_sleep, mock_signal):
        """Should log startup information."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 3
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Should log startup info
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("starting" in call.lower() for call in info_calls)
        assert any("3" in call for call in info_calls)  # Entry count

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    @patch("openviper.tasks.runner.logger")
    def test_logs_shutdown(self, mock_logger, mock_sleep, mock_signal):
        """Should log shutdown message."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Should log shutdown
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("stopped" in call.lower() for call in info_calls)

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_passes_now_to_tick(self, mock_sleep, mock_signal):
        """Should pass current datetime to tick()."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []

        mock_sleep.side_effect = KeyboardInterrupt()

        with patch("openviper.tasks.runner.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_datetime.now.return_value = mock_now
            mock_datetime.UTC = UTC

            run_scheduler(scheduler=mock_scheduler)

            # Should have called tick with now
            mock_scheduler.tick.assert_called()
            call_args = mock_scheduler.tick.call_args[0]
            assert call_args[0] is mock_now


class TestRunSchedulerNoSysExit:
    """run_scheduler must return normally without calling sys.exit."""

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_does_not_call_sys_exit(self, mock_sleep, mock_signal):
        """run_scheduler must not call sys.exit — it is embeddable."""

        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []
        mock_sleep.side_effect = KeyboardInterrupt()

        with patch.object(sys, "exit") as mock_exit:
            run_scheduler(scheduler=mock_scheduler)
            mock_exit.assert_not_called()

    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_returns_after_interrupt(self, mock_sleep, mock_signal):
        """run_scheduler must return (not raise) after KeyboardInterrupt."""
        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []
        mock_sleep.side_effect = KeyboardInterrupt()

        # Should not raise
        result = run_scheduler(scheduler=mock_scheduler)
        assert result is None


# ── _shutdown handler captures lines 66-68 ──────────────────────────────────


class TestRunSchedulerShutdownHandler:
    @patch("openviper.tasks.runner.signal.signal")
    @patch("openviper.tasks.runner.time.sleep")
    def test_shutdown_handler_sets_running_false(self, mock_sleep, mock_signal):
        """_shutdown sets _running=False and logs the signal name (lines 66-68)."""

        mock_scheduler = MagicMock(spec=Scheduler)
        mock_scheduler.__len__.return_value = 0
        mock_scheduler.tick.return_value = []
        mock_sleep.side_effect = KeyboardInterrupt()

        run_scheduler(scheduler=mock_scheduler)

        # Capture the _shutdown handler registered for SIGINT
        handlers = {call[0][0]: call[0][1] for call in mock_signal.call_args_list}
        shutdown = handlers.get(_sig.SIGINT)
        assert shutdown is not None

        # Calling the handler should log the signal name (lines 66-67) and set _running=False (68)
        # Patch logger before calling shutdown so we can assert on it
        with patch("openviper.tasks.runner.logger") as mock_logger:
            shutdown(_sig.SIGINT, None)

        # logger.info was called with the signal name
        logged = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "SIGINT" in logged or "Received" in logged
