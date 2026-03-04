from unittest.mock import patch

import dramatiq
import pytest

from openviper.tasks.broker import _RESULTS_AVAILABLE, get_broker, reset_broker, setup_broker


def _stub_settings(cfg: dict):
    return patch("openviper.tasks.broker._read_task_settings", return_value=cfg)


@pytest.fixture(autouse=True)
def clean_broker():
    reset_broker()
    yield
    reset_broker()


def test_setup_broker_stub():
    with _stub_settings({"broker": "stub"}):
        broker = setup_broker()
    assert isinstance(broker, dramatiq.brokers.stub.StubBroker)
    with _stub_settings({"broker": "stub"}):
        assert get_broker() is broker


def test_setup_broker_unknown_raises_value_error():
    with _stub_settings({"broker": "unknown"}):
        with pytest.raises(ValueError, match="unknown"):
            setup_broker()


def test_result_backend_setup():
    if not _RESULTS_AVAILABLE:
        pytest.skip("dramatiq[results] not installed")

    from unittest.mock import MagicMock

    mock_backend = MagicMock()
    with _stub_settings({"broker": "stub", "backend_url": "redis://localhost:6379/1"}):
        with patch("dramatiq.results.backends.redis.RedisBackend", return_value=mock_backend):
            broker = setup_broker()
    from dramatiq.results import Results

    assert any(isinstance(m, Results) for m in broker.middleware)
