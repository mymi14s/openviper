"""Broker factory for the openviper task system.

Supported backends (set via ``TASKS["broker"]`` in project settings):

* ``"redis"``    - :class:`dramatiq.brokers.redis.RedisBroker`  (default)
* ``"rabbitmq"`` - :class:`dramatiq.brokers.rabbitmq.RabbitmqBroker`
* ``"stub"``     - :class:`dramatiq.brokers.stub.StubBroker`  (testing only)

Full settings example::

    import os
    TASKS: dict[str, object] = {
        "broker": "redis",
        "url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "result_backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        "scheduler": True,             # enable the periodic task scheduler
        "tracking": True,              # record task results in DB
        "log_level": "DEBUG",          # optional - falls back to LOG_LEVEL
        "log_format": "json",          # optional - "text" (default) or "json"
        "log_to_file": True,           # write logs to logs/worker.log
        "log_dir": "/var/log/myapp",   # optional - defaults to {cwd}/logs
    }

``result_backend_url`` - Redis URL for Dramatiq's native result backend, which
                         lets callers retrieve an actor's return value via
                         ``message.get_result()``.  Requires ``dramatiq[redis]``.
                         Independent of the DB-based ``TaskTrackingMiddleware``.

The broker is created once and cached for the lifetime of the process.
Call :func:`reset_broker` to tear it down (primarily for testing).
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import dramatiq
from dramatiq.middleware.asyncio import AsyncIO

from openviper.conf import settings

if TYPE_CHECKING:
    from openviper.tasks.types import BrokerProtocol, TaskValue

RedisBroker: Callable[..., object] | None
try:
    RedisBroker = importlib.import_module("dramatiq.brokers.redis").RedisBroker
except (AttributeError, ImportError):  # fmt: skip
    RedisBroker = None

RabbitmqBroker: Callable[..., object] | None
try:
    RabbitmqBroker = importlib.import_module("dramatiq.brokers.rabbitmq").RabbitmqBroker
except (AttributeError, ImportError):  # fmt: skip
    RabbitmqBroker = None

StubBroker: Callable[..., object] | None
try:
    StubBroker = importlib.import_module("dramatiq.brokers.stub").StubBroker
except (AttributeError, ImportError):  # fmt: skip
    StubBroker = None

logger = logging.getLogger("openviper.tasks")

Results: Callable[..., object] | None
RedisBackend: Callable[..., object] | None
try:
    Results = importlib.import_module("dramatiq.results").Results
    redis_backend_module = importlib.import_module("dramatiq.results.backends.redis")
    RedisBackend = redis_backend_module.RedisBackend
except (AttributeError, ImportError):  # fmt: skip
    Results = None
    RedisBackend = None

TaskTrackingMiddleware: Callable[..., object] | None
SchedulerMiddleware: Callable[..., object] | None
try:
    from openviper.tasks.middleware import SchedulerMiddleware, TaskTrackingMiddleware
except ImportError:
    TaskTrackingMiddleware = None
    SchedulerMiddleware = None

setup_cleanup_task: Callable[[], None] | None
try:
    from openviper.tasks.results import setup_cleanup_task
except Exception:
    setup_cleanup_task = None

_broker: BrokerProtocol | None = None
_broker_lock = threading.Lock()


def get_broker() -> BrokerProtocol:
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
            broker = create_broker()
            _broker = broker
    return broker


# Kept for backwards-compat with openviper.setup().
setup_broker = get_broker


def reset_broker() -> None:
    """Tear down and forget the current broker.  Primarily for tests."""
    global _broker
    with _broker_lock:
        if _broker is not None:
            with contextlib.suppress(Exception):
                _broker.close()
        _broker = None


def read_task_settings() -> dict[str, TaskValue]:
    try:
        cfg = dict(getattr(settings, "TASKS", {}) or {})
    except Exception:
        return {}
    # Backward-compat: map legacy keys to current names.
    if "broker_url" in cfg and "url" not in cfg:
        cfg["url"] = cfg.pop("broker_url")
    if "backend_url" in cfg and "result_backend_url" not in cfg:
        cfg["result_backend_url"] = cfg.pop("backend_url")
    if "scheduler_enabled" in cfg and "scheduler" not in cfg:
        cfg["scheduler"] = bool(cfg.pop("scheduler_enabled"))
    if "tracking_enabled" in cfg and "tracking" not in cfg:
        cfg["tracking"] = bool(cfg.pop("tracking_enabled"))
    return cfg


def create_broker() -> BrokerProtocol:
    cfg = read_task_settings()
    backend_value = cfg.get("broker", "redis")
    backend = str(backend_value).lower()

    if backend == "redis":
        broker = make_redis_broker(cfg)
    elif backend == "rabbitmq":
        broker = make_rabbitmq_broker(cfg)
    elif backend == "stub":
        if StubBroker is None:
            raise ImportError(
                "dramatiq.brokers.stub.StubBroker is not available. "
                "Install dramatiq to use the stub backend."
            )
        broker = cast("BrokerProtocol", StubBroker())
    else:
        raise ValueError(
            f"Unknown TASKS broker {backend!r}. Valid choices: 'redis', 'rabbitmq', 'stub'."
        )

    broker.add_middleware(AsyncIO())

    if bool(cfg.get("tracking", True)):
        if TaskTrackingMiddleware is not None:
            try:
                broker.add_middleware(TaskTrackingMiddleware())
            except Exception as exc:
                logger.warning("Could not attach TaskTrackingMiddleware: %s", exc)
        else:
            logger.warning("TaskTrackingMiddleware is unavailable; tracking disabled.")
    else:
        logger.debug("Task result tracking disabled (set TASKS['tracking'] = False to enable.)")

    # Scheduler middleware - starts @periodic tick thread after worker boot.
    # Enable with TASKS["scheduler"] = True (default when TASKS is configured).
    if bool(cfg.get("scheduler", True)):
        if SchedulerMiddleware is not None:
            try:
                broker.add_middleware(SchedulerMiddleware())
            except Exception as exc:
                logger.warning("Could not attach SchedulerMiddleware: %s", exc)
        else:
            logger.warning("SchedulerMiddleware is unavailable; scheduler disabled.")

    # Automatic cleanup task - registers a daily cleanup job for old results.
    # Enable with TASKS["cleanup_enabled"] = True.
    if bool(cfg.get("cleanup_enabled", False)):
        if setup_cleanup_task is not None:
            try:
                setup_cleanup_task()
            except Exception as exc:
                logger.warning("Could not set up automatic cleanup task: %s", exc)
        else:
            logger.warning("setup_cleanup_task is unavailable; cleanup disabled.")

    # Dramatiq native result backend - enables message.get_result().
    # Requires TASKS["result_backend_url"] to be set (Redis URL).
    if cfg.get("result_backend_url"):
        if Results is not None and RedisBackend is not None:
            try:
                result_backend = RedisBackend(url=cfg["result_backend_url"])
                broker.add_middleware(Results(backend=result_backend))
            except Exception as exc:
                logger.warning("Could not attach result backend: %s", exc)
        else:
            logger.warning(
                "Dramatiq Results or RedisBackend not available; result_backend_url ignored."
            )

    dramatiq.set_broker(cast("dramatiq.Broker", broker))
    logger.debug(
        "Dramatiq broker ready: %s  (backend=%s)",
        type(broker).__name__,
        backend,
    )
    return broker


def make_redis_broker(cfg: dict[str, TaskValue]) -> BrokerProtocol:
    if RedisBroker is None:
        raise ImportError(
            "dramatiq.brokers.redis.RedisBroker is not available. "
            "Install dramatiq[redis] to use the Redis backend."
        )

    url = cfg.get("url") or "redis://localhost:6379/0"
    logger.debug("Connecting to Redis broker: %s", url.split("@")[-1])

    broker_kwargs: dict[str, TaskValue] = {"url": url}

    if "redis_max_connections" in cfg:
        val = cfg["redis_max_connections"]
        broker_kwargs["max_connections"] = int(val) if isinstance(val, (int, float, str)) else 50
    else:
        broker_kwargs["max_connections"] = 50

    if "redis_socket_timeout" in cfg:
        val = cfg["redis_socket_timeout"]
        broker_kwargs["socket_timeout"] = int(val) if isinstance(val, (int, float, str)) else 5
    if "redis_socket_connect_timeout" in cfg:
        val = cfg["redis_socket_connect_timeout"]
        broker_kwargs["socket_connect_timeout"] = (
            int(val) if isinstance(val, (int, float, str)) else 5
        )
    if "redis_socket_keepalive" in cfg:
        broker_kwargs["socket_keepalive"] = bool(cfg["redis_socket_keepalive"])

    return cast("BrokerProtocol", RedisBroker(**broker_kwargs))


def make_rabbitmq_broker(cfg: dict[str, TaskValue]) -> BrokerProtocol:
    if RabbitmqBroker is None:
        raise ImportError(
            "dramatiq.brokers.rabbitmq.RabbitmqBroker is not available. "
            "Install dramatiq[rabbitmq] to use the RabbitMQ backend."
        )

    url = cfg.get("url") or "amqp://guest:guest@localhost:5672/"
    logger.debug("Connecting to RabbitMQ broker: %s", url)
    return cast("BrokerProtocol", RabbitmqBroker(url=url))
