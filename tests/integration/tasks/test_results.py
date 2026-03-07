"""Integration tests for task results storage and query API."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from openviper.tasks.results import (
    batch_upsert_results,
    clean_old_results,
    delete_task_result,
    get_task_result,
    get_task_result_sync,
    get_task_stats,
    list_task_results,
    list_task_results_sync,
    reset_engine,
    upsert_result,
)


@pytest.fixture(autouse=True)
def setup_results_db(request):
    """Ensure we use an in-memory SQLite for results during tests."""
    # Use a unique name per test to avoid cross-test data leakage in shared cache
    db_name = f"results_test_{request.node.name}"
    db_url = f"sqlite:///file:{db_name}?mode=memory&cache=shared"
    with patch("openviper.tasks.results._resolve_db_url", return_value=db_url):
        reset_engine()
        yield
        reset_engine()


def test_upsert_and_get_result_sync():
    """Verify sync upsert and retrieval."""
    msg_id = "test-123"
    upsert_result(
        msg_id,
        actor_name="test_actor",
        status="success",
        result={"foo": "bar"},
    )

    row = get_task_result_sync(msg_id)
    assert row is not None
    assert row["message_id"] == msg_id
    assert row["actor_name"] == "test_actor"
    assert row["status"] == "success"
    assert row["result"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_upsert_and_get_result_async():
    """Verify async retrieval wrapper."""
    msg_id = "async-123"
    upsert_result(msg_id, status="running")

    row = await get_task_result(msg_id)
    assert row is not None
    assert row["status"] == "running"


def test_batch_upsert():
    """Verify batch write logic."""
    events = [
        ("m1", {"status": "pending"}),
        ("m2", {"status": "success", "result": 100}),
    ]
    batch_upsert_results(events)

    r1 = get_task_result_sync("m1")
    r2 = get_task_result_sync("m2")
    assert r1["status"] == "pending"
    assert r2["result"] == 100


def test_list_results_filters():
    """Verify listing and filtering."""
    upsert_result("a", actor_name="alpha", status="success")
    upsert_result("b", actor_name="beta", status="failure")
    upsert_result("c", actor_name="alpha", status="failure")

    # Filter by status
    successes = list_task_results_sync(status="success")
    assert len(successes) == 1
    assert successes[0]["message_id"] == "a"

    # Filter by actor
    alphas = list_task_results_sync(actor_name="alpha")
    assert len(alphas) == 2

    # Combined
    alpha_fails = list_task_results_sync(actor_name="alpha", status="failure")
    assert len(alpha_fails) == 1
    assert alpha_fails[0]["message_id"] == "c"


@pytest.mark.asyncio
async def test_list_results_async():
    """Verify async listing wrapper."""
    upsert_result("async-a", status="success")

    rows = await list_task_results(status="success")
    assert any(r["message_id"] == "async-a" for r in rows)


def test_json_column_deserialization():
    """Verify that JSON columns are converted back to Python objects."""
    msg_id = "json-test"
    # Fields that get JSON-encoded: args, kwargs, result
    upsert_result(
        msg_id,
        args=[1, 2, 3],
        kwargs={"active": True},
        result={"val": 1.5},
    )

    row = get_task_result_sync(msg_id)
    assert row["args"] == [1, 2, 3]
    assert row["kwargs"] == {"active": True}
    assert row["result"] == {"val": 1.5}


def test_datetime_serialization():
    """Verify datetime columns are handled and normalized to ISO strings."""
    msg_id = "time-test"
    now = datetime.now(UTC)
    upsert_result(msg_id, enqueued_at=now)

    row = get_task_result_sync(msg_id)
    assert isinstance(row["enqueued_at"], str)
    # Basic ISO format check
    assert "T" in row["enqueued_at"]


def test_delete_result():
    """Verify result deletion."""
    upsert_result("del-me", status="success")
    assert get_task_result_sync("del-me") is not None

    delete_task_result("del-me")
    assert get_task_result_sync("del-me") is None


def test_clean_old_results():
    """Verify cleanup of old records."""
    from datetime import timedelta

    old = datetime.now(UTC) - timedelta(days=10)
    new = datetime.now(UTC)

    upsert_result("old", status="success", completed_at=old)
    upsert_result("new", status="success", completed_at=new)

    # Clean results older than 5 days
    deleted = clean_old_results(days=5)
    assert deleted == 1
    assert get_task_result_sync("old") is None
    assert get_task_result_sync("new") is not None


@pytest.mark.asyncio
async def test_get_task_stats():
    """Verify statistics aggregation."""
    upsert_result("s1", status="success")
    upsert_result("s2", status="success")
    upsert_result("f1", status="failure")
    upsert_result("p1", status="pending")

    stats = await get_task_stats()
    assert stats["success"] == 2
    assert stats["failure"] == 1
    assert stats["pending"] == 1
    assert stats["total"] == 4


def test_batch_upsert_serialization_failure():
    """Verify that batch_upsert handles JSON serialization failures gracefully."""
    # Create an object that cannot be JSON serialized
    unserializable = object()
    events = [("fail-val", {"args": [unserializable]})]
    # This should not raise, but instead use repr() or catch the error
    batch_upsert_results(events)

    res = get_task_result_sync("fail-val")
    assert res is not None
    # Depending on implementation, it might have the repr or be skipped.
    # The code uses repr() on failure.
    assert "<object object at" in res["args"]


@pytest.mark.asyncio
async def test_get_task_stats_no_engine():
    """Verify get_task_stats handles no-engine case."""
    with patch("openviper.tasks.results._get_engine", side_effect=RuntimeError("no engine")):
        stats = await get_task_stats()
        assert stats["total"] == 0


def test_batch_upsert_no_engine():
    """Verify batch_upsert handles no-engine case."""
    with patch("openviper.tasks.results._get_engine", side_effect=RuntimeError("no engine")):
        # Should just return without error
        batch_upsert_results([("m1", {"status": "ok"})])


def test_to_sync_url_helper():
    """Verify URL conversion helper for different dialects."""
    from openviper.tasks.results import _to_sync_url

    # Postgres: it will try to find an installed driver like psycopg2
    res = _to_sync_url("postgresql+asyncpg://user:pass@host/db")
    assert res.startswith("postgresql+") or res.startswith("postgresql://")
    assert "asyncpg" not in res

    # MySQL
    assert _to_sync_url("mysql+aiomysql://user:pass@host/db") == "mysql+pymysql://user:pass@host/db"
    # No change
    assert _to_sync_url("sqlite:///file.db") == "sqlite:///file.db"


def test_reset_engine_smoke():
    """Verify reset_engine can be called safely."""
    from openviper.tasks.results import reset_engine

    reset_engine()
    # If we call it again, it should still be fine
    reset_engine()
