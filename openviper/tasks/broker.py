"""Broker factory for the openviper task system.

Supported backends (set via ``TASKS["broker"]`` in project settings):

* ``"redis"``    — :class:`dramatiq.brokers.redis.RedisBroker`  (default)
* ``"rabbitmq"`` — :class:`dramatiq.brokers.rabbitmq.RabbitmqBroker`
* ``"stub"``     — :class:`dramatiq.brokers.stub.StubBroker`  (testing only)

Full settings example::

    import os
    from typing import Any

    TASKS: dict[str, Any] = {
        "enabled": 1,                  # required — worker will not start without this
        "broker": "redis",
        "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        "scheduler_enabled": 1,        # 1/0 or True/False
        "tracking_enabled": 1,         # 1/0 or True/False
        "log_level": "DEBUG",          # optional — falls back to LOG_LEVEL
        "log_format": "json",          # optional — "text" (default) or "json"
        "log_to_file": 1,              # 1/0 or True/False
        "log_dir": "/var/log/myapp",   # optional — defaults to {cwd}/logs
    }

``backend_url``     — Redis URL for Dramatiq's native result backend, which lets
                      callers retrieve an actor's return value via
                      ``message.get_result()``.  Requires ``dramatiq[redis]``.
                      Independent of the DB-based ``TaskTrackingMiddleware``.

The broker is created once and cached for the lifetime of the process.
Call :func:`reset_broker` to tear it down (primarily for testing).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import dramatiq
from dramatiq.middleware.asyncio import AsyncIO

from openviper.conf import settings

logger = logging.getLogger("openviper.tasks")

# True when dramatiq[redis] results extras are importable.
try:
    from dramatiq.results import Results as _Results  # noqa: F401

    _RESULTS_AVAILABLE = True
except ImportError:
    _RESULTS_AVAILABLE = False

_broker: Any = None
_broker_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_broker() -> Any:
    """Return the process-level broker, creating it on first call.

    Uses a double-checked lock pattern.  A local snapshot of the global is
    returned so the caller is never exposed to a ``None`` value that could
    result from a concurrent :func:`reset_broker` call landing between the
    lock release and the ``return`` statement.
    """
    global _broker
    # Fast path: take a local snapshot (CPython GIL makes the ref-read atomic).
    broker = _broker
    if broker is not None:
        return broker
    with _broker_lock:
        # Re-read inside the lock; another thread may have won the race.
        broker = _broker
        if broker is None:
            broker = _create_broker()
            _broker = broker  # write inside the lock
    # Return the local variable — never re-read the global after lock release.
    return broker


# Kept for backwards-compat with openviper.setup() and any existing imports.
setup_broker = get_broker


def reset_broker() -> None:
    """Tear down and forget the current broker.  Primarily for tests."""
    global _broker
    with _broker_lock:
        if _broker is not None:
            try:
                _broker.close()
            except Exception:
                pass
        _broker = None


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------


def _read_task_settings() -> dict[str, Any]:
    try:
        return dict(getattr(settings, "TASKS", {}) or {})
    except Exception:
        return {}


def _create_broker() -> Any:
    cfg = _read_task_settings()
    backend = cfg.get("broker", "redis").lower()

    if backend == "redis":
        broker = _make_redis_broker(cfg)
    elif backend == "rabbitmq":
        broker = _make_rabbitmq_broker(cfg)
    elif backend == "stub":
        from dramatiq.brokers.stub import StubBroker

        broker = StubBroker()
    else:
        raise ValueError(
            f"Unknown TASKS broker {backend!r}. " "Valid choices: 'redis', 'rabbitmq', 'stub'."
        )

    # AsyncIO middleware — enables `async def` actor functions.
    broker.add_middleware(AsyncIO())

    # Result-tracking middleware — records every task lifecycle event to the
    # database so callers can poll for completion / inspect failures.
    # Enable with TASKS["tracking_enabled"] = 1 or True.
    if bool(cfg.get("tracking_enabled", False)):
        try:
            from openviper.tasks.middleware import TaskTrackingMiddleware

            broker.add_middleware(TaskTrackingMiddleware())
        except Exception as exc:
            logger.warning("Could not attach TaskTrackingMiddleware: %s", exc)
    else:
        logger.info("Task result tracking disabled (set TASKS['tracking_enabled'] = 1 to enable).")

    # Scheduler middleware — starts @periodic tick thread after worker boot.
    # Enable with TASKS["scheduler_enabled"] = 1 or True.
    if bool(cfg.get("scheduler_enabled", False)):
        try:
            from openviper.tasks.middleware import SchedulerMiddleware

            broker.add_middleware(SchedulerMiddleware())
        except Exception as exc:
            logger.warning("Could not attach SchedulerMiddleware: %s", exc)

    # Dramatiq native result backend — enables message.get_result().
    # Requires TASKS["backend_url"] to be set (Redis URL).
    if cfg.get("backend_url"):
        try:
            from dramatiq.results import Results
            from dramatiq.results.backends.redis import RedisBackend

            result_backend = RedisBackend(url=cfg["backend_url"])
            broker.add_middleware(Results(backend=result_backend))
            logger.info(
                "Dramatiq result backend: %s",
                cfg["backend_url"].split("@")[-1],
            )
        except Exception as exc:
            logger.warning("Could not attach result backend: %s", exc)

    dramatiq.set_broker(broker)
    logger.info(
        "Dramatiq broker ready: %s  (backend=%s)",
        type(broker).__name__,
        backend,
    )
    return broker


def _make_redis_broker(cfg: dict[str, Any]) -> Any:
    from dramatiq.brokers.redis import RedisBroker

    url = cfg.get("broker_url") or "redis://localhost:6379/0"
    logger.debug("Connecting to Redis broker: %s", url)
    return RedisBroker(url=url)


def _make_rabbitmq_broker(cfg: dict[str, Any]) -> Any:
    from dramatiq.brokers.rabbitmq import RabbitmqBroker

    url = cfg.get("broker_url") or "amqp://guest:guest@localhost:5672/"
    logger.debug("Connecting to RabbitMQ broker: %s", url)
    return RabbitmqBroker(url=url)
