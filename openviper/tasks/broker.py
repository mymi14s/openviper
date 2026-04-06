"""Broker factory for the openviper task system.

Supported backends (set via ``TASKS["broker"]`` in project settings):

* ``"redis"``    — :class:`dramatiq.brokers.redis.RedisBroker`  (default)
* ``"rabbitmq"`` — :class:`dramatiq.brokers.rabbitmq.RabbitmqBroker`
* ``"stub"``     — :class:`dramatiq.brokers.stub.StubBroker`  (testing only)

Full settings example::

    import os
    from typing import Any

    TASKS: dict[str, Any] = {
        "enabled": 1,
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

import contextlib
import logging
import threading
from typing import Any

import dramatiq
from dramatiq.middleware.asyncio import AsyncIO

from openviper.conf import settings

try:
    from dramatiq.brokers.redis import RedisBroker
except ImportError:
    RedisBroker = None  # type: ignore[misc, assignment]

try:
    from dramatiq.brokers.rabbitmq import RabbitmqBroker
except ImportError:
    RabbitmqBroker = None  # type: ignore[misc, assignment]

try:
    from dramatiq.brokers.stub import StubBroker
except ImportError:
    StubBroker = None  # type: ignore[misc, assignment]

logger = logging.getLogger("openviper.tasks")

# True when dramatiq[redis] results extras are importable.
try:
    from dramatiq.results import Results
    from dramatiq.results.backends.redis import RedisBackend
except ImportError:
    Results = None  # type: ignore[assignment, misc]
    RedisBackend = None  # type: ignore[assignment, misc]

try:
    from openviper.tasks.middleware import SchedulerMiddleware, TaskTrackingMiddleware
except ImportError:
    TaskTrackingMiddleware = None  # type: ignore[assignment, misc]
    SchedulerMiddleware = None  # type: ignore[assignment, misc]

try:
    from openviper.tasks.results import setup_cleanup_task
except Exception:
    setup_cleanup_task = None  # type: ignore[assignment]

_broker: Any = None
_broker_lock = threading.Lock()


def get_broker() -> Any:
    """Return the process-level broker, creating it on first call.

    Uses a double-checked lock pattern.  A local snapshot of the global is
    returned so the caller is never exposed to a ``None`` value that could
    result from a concurrent :func:`reset_broker` call landing between the
    lock release and the ``return`` statement.
    """
    global _broker
    broker = _broker
    if broker is not None:
        return broker
    with _broker_lock:
        broker = _broker
        if broker is None:
            broker = _create_broker()
            _broker = broker  # write inside the lock
    return broker


# Kept for backwards-compat with openviper.setup() and any existing imports.
setup_broker = get_broker


def reset_broker() -> None:
    """Tear down and forget the current broker.  Primarily for tests."""
    global _broker
    with _broker_lock:
        if _broker is not None:
            with contextlib.suppress(Exception):
                _broker.close()
        _broker = None


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
        if StubBroker is None:
            raise ImportError(
                "dramatiq.brokers.stub.StubBroker is not available. "
                "Install dramatiq to use the stub backend."
            )
        broker = StubBroker()
    else:
        raise ValueError(
            f"Unknown TASKS broker {backend!r}. Valid choices: 'redis', 'rabbitmq', 'stub'."
        )

    broker.add_middleware(AsyncIO())

    if bool(cfg.get("tracking_enabled", False)):
        if TaskTrackingMiddleware is not None:
            try:
                broker.add_middleware(TaskTrackingMiddleware())
            except Exception as exc:
                logger.warning("Could not attach TaskTrackingMiddleware: %s", exc)
        else:
            logger.warning("TaskTrackingMiddleware is unavailable; tracking disabled.")
    else:
        logger.debug("Task result tracking disabled (set TASKS['tracking_enabled'] = 1 to enable.)")

    # Scheduler middleware — starts @periodic tick thread after worker boot.
    # Enable with TASKS["scheduler_enabled"] = 1 or True.
    if bool(cfg.get("scheduler_enabled", False)):
        if SchedulerMiddleware is not None:
            try:
                broker.add_middleware(SchedulerMiddleware())
            except Exception as exc:
                logger.warning("Could not attach SchedulerMiddleware: %s", exc)
        else:
            logger.warning("SchedulerMiddleware is unavailable; scheduler disabled.")

    # Automatic cleanup task — registers a daily cleanup job for old results.
    # Enable with TASKS["cleanup_enabled"] = 1 or True.
    if bool(cfg.get("cleanup_enabled", False)):
        if setup_cleanup_task is not None:
            try:
                setup_cleanup_task()
            except Exception as exc:
                logger.warning("Could not set up automatic cleanup task: %s", exc)
        else:
            logger.warning("setup_cleanup_task is unavailable; cleanup disabled.")

    # Dramatiq native result backend — enables message.get_result().
    # Requires TASKS["backend_url"] to be set (Redis URL).
    if cfg.get("backend_url"):
        if Results is not None and RedisBackend is not None:
            try:
                result_backend = RedisBackend(url=cfg["backend_url"])  # type: ignore[no-untyped-call]
                broker.add_middleware(Results(backend=result_backend))  # type: ignore[no-untyped-call]
            except Exception as exc:
                logger.warning("Could not attach result backend: %s", exc)
        else:
            logger.warning("Dramatiq Results or RedisBackend not available; backend_url ignored.")

    dramatiq.set_broker(broker)
    logger.debug(
        "Dramatiq broker ready: %s  (backend=%s)",
        type(broker).__name__,
        backend,
    )
    return broker


def _make_redis_broker(cfg: dict[str, Any]) -> Any:
    if RedisBroker is None:
        raise ImportError(
            "dramatiq.brokers.redis.RedisBroker is not available. "
            "Install dramatiq[redis] to use the Redis backend."
        )

    url = cfg.get("broker_url") or "redis://localhost:6379/0"
    logger.debug("Connecting to Redis broker: %s", url.split("@")[-1])

    broker_kwargs: dict[str, Any] = {"url": url}

    if "redis_max_connections" in cfg:
        broker_kwargs["max_connections"] = int(cfg["redis_max_connections"])
    else:
        broker_kwargs["max_connections"] = 50

    if "redis_socket_timeout" in cfg:
        broker_kwargs["socket_timeout"] = int(cfg["redis_socket_timeout"])
    if "redis_socket_connect_timeout" in cfg:
        broker_kwargs["socket_connect_timeout"] = int(cfg["redis_socket_connect_timeout"])
    if "redis_socket_keepalive" in cfg:
        broker_kwargs["socket_keepalive"] = bool(cfg["redis_socket_keepalive"])

    return RedisBroker(**broker_kwargs)  # type: ignore[no-untyped-call]


def _make_rabbitmq_broker(cfg: dict[str, Any]) -> Any:
    if RabbitmqBroker is None:
        raise ImportError(
            "dramatiq.brokers.rabbitmq.RabbitmqBroker is not available. "
            "Install dramatiq[rabbitmq] to use the RabbitMQ backend."
        )

    url = cfg.get("broker_url") or "amqp://guest:guest@localhost:5672/"
    logger.debug("Connecting to RabbitMQ broker: %s", url)
    return RabbitmqBroker(url=url)
