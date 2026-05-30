"""Tests for expanded OpenViper testing helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from openviper.testing.cache import TestCache, assert_cache_key
from openviper.testing.events import EventRecorder, assert_event_count, assert_event_payload
from openviper.testing.mail import (
    InMemoryMailBackend,
    assert_email_count,
    assert_email_recipient,
    assert_email_subject,
)
from openviper.testing.openapi import assert_request_schema, assert_response_schema
from openviper.testing.snapshot import Snapshot
from openviper.testing.storage import assert_storage_path
from openviper.testing.tasks import (
    EagerTaskRunner,
    TaskQueue,
    assert_task_count,
    assert_task_queued,
)


async def test_in_memory_mail_backend_records_messages() -> None:
    outbox = []
    backend = InMemoryMailBackend(outbox)

    await backend.send("Welcome", ["user@example.com"], body="Hello")

    assert_email_count(outbox, 1)
    assert_email_subject(outbox[0], "Welcome")
    assert_email_recipient(outbox[0], "user@example.com")


def test_event_recorder_asserts_payloads() -> None:
    recorder = EventRecorder()
    recorder.record("user.created", user_id=1)

    assert_event_count(recorder, "user.created", 1)
    assert_event_payload(recorder, "user.created", user_id=1)


async def test_task_queue_and_eager_runner() -> None:
    queue = TaskQueue()
    queue.add("send_email", "user@example.com")

    async def task(value: int) -> int:
        return value + 1

    assert_task_queued(queue, "send_email")
    assert_task_count(queue, 1)
    assert await EagerTaskRunner().run(task, 1) == 2


async def test_cache_assertion() -> None:
    cache = TestCache()

    await cache.set("key", "value")

    assert_cache_key(cache, "key")


def test_openapi_schema_assertions() -> None:
    schema = {
        "paths": {
            "/users": {
                "post": {
                    "requestBody": {},
                    "responses": {"201": {"description": "Created"}},
                }
            }
        }
    }

    assert_request_schema(schema, "/users", "post")
    assert_response_schema(schema, "/users", "post", 201)


def test_storage_path_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()

    with pytest.raises(AssertionError):
        assert_storage_path(root, tmp_path.parent)


def test_snapshot_creates_and_compares_file(tmp_path: Path) -> None:
    snapshot = Snapshot(tmp_path)

    snapshot.assert_matches("payload.json", {"ok": True})
    snapshot.assert_matches("payload.json", {"ok": True})
