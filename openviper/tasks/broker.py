"""Dramatiq broker factory from ``settings.TASKS`` configuration.

Supports Redis, RabbitMQ, SQS, PostgreSQL, and Stub brokers.
The broker is lazily initialised on first access and cached for the
process lifetime.
"""

from __future__ import annotations

import typing as t

import dramatiq

from openviper.conf import settings
from openviper.tasks.exceptions import OpenViperTasksConfigurationError

if t.TYPE_CHECKING:
    from dramatiq import Broker

    from openviper.conf.types import ConfigMap

try:
    import dramatiq.brokers.redis
except ImportError:
    dramatiq.brokers.redis = None  # type: ignore[assignment]

try:
    import dramatiq.brokers.rabbitmq
except ImportError:
    dramatiq.brokers.rabbitmq = None  # type: ignore[assignment]

try:
    import dramatiq.brokers.stub
except ImportError:
    dramatiq.brokers.stub = None  # type: ignore[assignment]

try:
    import dramatiq_sqs
except ImportError:
    dramatiq_sqs = None

try:
    from dramatiq_pg import PostgresBroker
except ImportError:
    PostgresBroker = None

try:
    import psycopg2.pool
except ImportError:
    psycopg2 = None

try:
    import prometheus_client as prometheus_client
except ImportError:
    prometheus_client = None  # type: ignore

try:
    from dramatiq.broker import default_middleware as dramatiq_defaults
except ImportError:
    dramatiq_defaults = None  # type: ignore[assignment]

try:
    from dramatiq.middleware.prometheus import Prometheus as PrometheusMiddleware
except ImportError:
    PrometheusMiddleware = None  # type: ignore[assignment,misc]

BROKER_INSTANCE: Broker | None = None

SUPPORTED_BROKERS = frozenset({"redis", "rabbitmq", "sqs", "postgresql", "stub"})


def default_middleware() -> list:
    """Return Dramatiq default middleware, excluding Prometheus when
    ``prometheus_client`` is not installed."""
    if dramatiq_defaults is None:
        return []
    middleware = [m() for m in dramatiq_defaults]
    if prometheus_client is None and PrometheusMiddleware is not None:
        middleware = [m for m in middleware if not isinstance(m, PrometheusMiddleware)]
    return middleware


def get_broker() -> Broker:
    """Return the global Dramatiq broker, creating it if necessary.

    Raises :class:`OpenViperTasksConfigurationError` on invalid config.
    """
    global BROKER_INSTANCE
    if BROKER_INSTANCE is not None:
        return BROKER_INSTANCE

    cfg = settings.TASKS
    if not isinstance(cfg, dict):
        cfg = {}

    broker_type = str(cfg.get("broker", "redis")).lower()
    broker_url = str(cfg.get("broker_url", ""))

    if broker_type == "redis":
        require_broker_url(broker_type, broker_url)
        broker = create_redis_broker(broker_url, cfg)
    elif broker_type == "rabbitmq":
        require_broker_url(broker_type, broker_url)
        broker = create_rabbitmq_broker(broker_url, cfg)
    elif broker_type == "sqs":
        broker = create_sqs_broker(cfg)
    elif broker_type == "postgresql":
        require_broker_url(broker_type, broker_url)
        broker = create_postgresql_broker(broker_url, cfg)
    elif broker_type == "stub":
        broker = create_stub_broker(cfg)
    else:
        raise OpenViperTasksConfigurationError(
            [
                f"Unsupported broker type: {broker_type!r}. "
                f"Choose from: {', '.join(sorted(SUPPORTED_BROKERS))}"
            ]
        )

    BROKER_INSTANCE = broker
    return BROKER_INSTANCE


def register_broker(broker: Broker) -> Broker:
    """Set *broker* as the global Dramatiq broker and return it."""
    dramatiq.set_broker(broker)
    return broker


def require_broker_url(broker_type: str, broker_url: str) -> None:
    """Raise :class:`OpenViperTasksConfigurationError` when *broker_url* is empty."""
    if not broker_url:
        raise OpenViperTasksConfigurationError(
            [f"TASKS['broker_url'] is required for the {broker_type} broker"]
        )


def create_redis_broker(url: str, cfg: ConfigMap) -> Broker:
    """Create a RedisBroker from *url*."""
    if dramatiq.brokers.redis is None:
        raise OpenViperTasksConfigurationError(
            ["redis package is not installed. Install with: pip install 'openviper[tasks-redis]'"]
        )
    return register_broker(
        dramatiq.brokers.redis.RedisBroker(url=url, middleware=default_middleware())
    )


def create_rabbitmq_broker(url: str, cfg: ConfigMap) -> Broker:
    """Create a RabbitmqBroker from *url*."""
    if dramatiq.brokers.rabbitmq is None:
        raise OpenViperTasksConfigurationError(
            ["pika package is not installed. Install with: pip install 'openviper[tasks-rabbitmq]'"]
        )
    return register_broker(
        dramatiq.brokers.rabbitmq.RabbitmqBroker(url=url, middleware=default_middleware())
    )


def create_sqs_broker(cfg: ConfigMap) -> Broker:
    """Create an SQSBroker from TASKS configuration."""
    if dramatiq_sqs is None:
        raise OpenViperTasksConfigurationError(
            ["dramatiq_sqs is not installed. Install with: pip install 'openviper[tasks-sqs]'"]
        )
    namespace = cfg.get("sqs_namespace", "openviper")
    endpoint_url = cfg.get("sqs_endpoint_url")
    user_middleware = cfg.get("middleware", [])
    if not isinstance(user_middleware, list):
        user_middleware = []

    kwargs: ConfigMap = {"namespace": namespace}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    kwargs["middleware"] = default_middleware() + user_middleware

    return register_broker(dramatiq_sqs.SQSBroker(**kwargs))


def create_postgresql_broker(url: str, cfg: ConfigMap) -> Broker:
    """Create a PostgresBroker from *url*."""
    if PostgresBroker is None or psycopg2 is None:
        raise OpenViperTasksConfigurationError(
            [
                "dramatiq-pg or psycopg2 is not installed. "
                "Install with: pip install 'openviper[tasks-postgresql]'"
            ]
        )
    pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=cfg.get("pg_min_connections", 2),
        maxconn=cfg.get("pg_max_connections", 10),
        dsn=url,
    )
    return register_broker(PostgresBroker(pool, middleware=default_middleware()))


def create_stub_broker(cfg: ConfigMap) -> Broker:
    """Create a StubBroker for testing."""
    if dramatiq.brokers.stub is None:
        raise OpenViperTasksConfigurationError(
            ["dramatiq.brokers.stub is not available. Ensure dramatiq is installed correctly."]
        )
    return register_broker(dramatiq.brokers.stub.StubBroker(middleware=default_middleware()))


def reset_broker() -> None:
    """Reset the cached broker instance (for testing)."""
    global BROKER_INSTANCE
    BROKER_INSTANCE = None
