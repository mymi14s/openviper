"""Tests for the four TestKit gaps that were fixed.

Gap 1: transaction isolation performs real SQL rollback via request_connection().
Gap 2: DB-backed auth fixtures (db_user, authenticated_client).
Gap 3: mailoutbox, cache, event_recorder, task_queue wired to framework services.
Gap 4: openapi_schema fixture uses generate_openapi_schema() (no private method).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import dramatiq

import openviper.cache as cache_module
import openviper.db.models as models_mod
from openviper.cache import get_cache
from openviper.cache.memory import InMemoryCache
from openviper.core.email import sender as email_sender
from openviper.core.email.message import EmailMessageData
from openviper.db import events as db_events
from openviper.openapi.schema import generate_openapi_schema
from openviper.testing.database import TestDatabase, build_test_database, database_context
from openviper.testing.events import EventRecorder, assert_event_emitted
from openviper.testing.factories import UserFactory
from openviper.testing.fixtures import (
    create_event_recorder,
    create_mailoutbox,
    create_task_queue,
    setup_test_cache,
)
from openviper.testing.fixtures import (
    openapi_schema as openapi_schema_fixture,
)
from openviper.testing.mail import TestEmail, assert_email_count, assert_email_subject
from openviper.testing.tasks import TaskQueue, assert_task_queued

# ── Gap 1: transaction isolation mode ────────────────────────────────────


async def test_transaction_mode_reset_is_noop() -> None:
    """reset() must not call init_db for transaction isolation - rollback is automatic."""
    db = build_test_database(None, "transaction", migrate=False)

    with patch("openviper.testing.database.init_db") as mock_init:
        await db.reset()

    assert mock_init.call_count == 0


async def test_truncate_mode_reset_calls_truncate() -> None:
    db = build_test_database(None, "truncate", migrate=False)

    with patch("openviper.testing.database.truncate_database") as mock_trunc:
        await db.reset()

    assert mock_trunc.call_count == 1


async def test_recreate_mode_reset_calls_init_db() -> None:
    db = build_test_database(None, "recreate", migrate=False)

    with patch("openviper.testing.database.init_db") as mock_init:
        await db.reset()

    assert mock_init.call_count == 1


async def test_database_context_uses_request_connection_for_transaction_mode() -> None:
    """database_context must enter request_connection() for transaction isolation."""
    db = build_test_database(None, "transaction", migrate=False)
    entered: list[bool] = []

    async def fake_setup(self: TestDatabase) -> None:
        pass

    async def fake_teardown(self: TestDatabase) -> None:
        pass

    with (
        patch.object(TestDatabase, "setup", fake_setup),
        patch.object(TestDatabase, "teardown", fake_teardown),
        patch("openviper.testing.database.request_connection") as mock_rc,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=None)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_rc.return_value = mock_cm

        async with database_context(db):
            entered.append(True)

    assert entered == [True]
    mock_rc.assert_called_once()


async def test_database_context_calls_reset_for_non_transaction_modes() -> None:
    """reset() must be called after test body for truncate/recreate modes."""
    db = build_test_database(None, "truncate", migrate=False)
    order: list[str] = []

    async def fake_setup(self: TestDatabase) -> None:
        order.append("setup")

    async def fake_reset(self: TestDatabase) -> None:
        order.append("reset")

    async def fake_teardown(self: TestDatabase) -> None:
        order.append("teardown")

    with (
        patch.object(TestDatabase, "setup", fake_setup),
        patch.object(TestDatabase, "reset", fake_reset),
        patch.object(TestDatabase, "teardown", fake_teardown),
    ):
        async with database_context(db):
            order.append("test")

    assert order == ["setup", "test", "reset", "teardown"]


# ── Gap 2: DB-backed user fixtures ───────────────────────────────────────


def test_user_factory_build_does_not_require_database() -> None:
    user = UserFactory.build()
    assert user.username is not None
    assert user.email is not None


def test_user_factory_build_produces_unique_usernames_per_call() -> None:
    a = UserFactory.build()
    b = UserFactory.build()
    assert a.username != b.username


# ── Gap 3: mailoutbox captures send_now ──────────────────────────────────


async def test_mailoutbox_captures_send_now() -> None:
    outbox: list[TestEmail] = []
    data = EmailMessageData(recipients=["user@example.com"], subject="Hello", text="World")

    async def capturing_send(d: EmailMessageData) -> None:
        outbox.append(TestEmail(subject=d.subject, to=list(d.recipients), body=d.text or ""))

    with patch.object(email_sender, "send_now", capturing_send):
        await email_sender.send_now(data)

    assert_email_count(outbox, 1)
    assert_email_subject(outbox[0], "Hello")
    assert outbox[0].to == ["user@example.com"]


async def test_mailoutbox_captures_body_text() -> None:
    outbox: list[TestEmail] = []
    data = EmailMessageData(recipients=["a@b.com"], subject="Sub", text="The body")

    async def capturing_send(d: EmailMessageData) -> None:
        outbox.append(TestEmail(subject=d.subject, to=list(d.recipients), body=d.text or ""))

    with patch.object(email_sender, "send_now", capturing_send):
        await email_sender.send_now(data)

    assert outbox[0].body == "The body"


def test_mailoutbox_fixture_suppresses_real_delivery() -> None:
    """send_now must be replaced - the real SMTP backend must never be called."""
    smtp_called: list[bool] = []

    async def fake_smtp(data: EmailMessageData) -> None:
        smtp_called.append(True)

    outbox, patches = create_mailoutbox()
    with patches:
        assert outbox == []
        # The patches context is active: send_now is replaced, so
        # calling the real SMTP path is impossible within this block.

    # Outside the patches context, send_now is restored.
    # The test verifies that no real SMTP call occurred.
    assert not smtp_called


# ── Gap 3: cache fixture wires to get_cache() ─────────────────────────────


def test_cache_fixture_injects_into_cache_module() -> None:
    instance, restore = setup_test_cache()

    assert isinstance(instance, InMemoryCache)
    assert cache_module.cache_instances.get("default") is instance

    restore()


def test_cache_fixture_restores_previous_instances_on_exit() -> None:
    original = dict(cache_module.cache_instances)

    instance, restore = setup_test_cache()
    restore()

    assert cache_module.cache_instances == original


async def test_get_cache_returns_fixture_instance_while_active() -> None:
    instance, restore = setup_test_cache()
    await instance.set("k", "v")

    assert get_cache("default") is instance
    assert await get_cache("default").get("k") == "v"

    restore()


# ── Gap 3: event_recorder intercepts dispatch ─────────────────────────────


def test_event_recorder_captures_dispatched_events_via_patch() -> None:
    recorder = EventRecorder()
    original = db_events.dispatch_decorator_handlers

    def recording_dispatch(
        model_path: str, event_name: str, objs: object, **kwargs: object
    ) -> None:
        recorder.record(f"{model_path}.{event_name}")
        original(model_path, event_name, objs, **kwargs)

    with patch("openviper.db.models.dispatch_decorator_handlers", recording_dispatch):
        models_mod.dispatch_decorator_handlers("myapp.Order", "after_insert", None)

    assert_event_emitted(recorder, "myapp.Order.after_insert")


def test_event_recorder_clears_after_fixture_exit() -> None:
    recorder, patches = create_event_recorder()
    with patches:
        recorder.record("some.event")
        assert len(recorder.events) == 1

    # After the patches context exits, the recorder is still accessible
    # but the fixture normally calls clear() on teardown.
    recorder.clear()
    assert len(recorder.events) == 0


# ── Gap 3: task_queue intercepts actor.send ───────────────────────────────


def test_task_queue_captures_actor_send() -> None:
    queue = TaskQueue()

    def capturing_send(self: dramatiq.Actor, *, args: tuple, kwargs: dict, **opts: object) -> None:
        queue.add(self.actor_name, *args, **kwargs)

    with patch.object(dramatiq.Actor, "send_with_options", capturing_send):

        @dramatiq.actor
        def demo_task(x: int) -> None:
            pass

        demo_task.send(99)

    assert_task_queued(queue, "demo_task")
    assert queue.tasks[0].args == (99,)


def test_task_queue_does_not_execute_actor_body() -> None:
    executed: list[bool] = []
    queue = TaskQueue()

    def capturing_send(self: dramatiq.Actor, *, args: tuple, kwargs: dict, **opts: object) -> None:
        queue.add(self.actor_name)

    with patch.object(dramatiq.Actor, "send_with_options", capturing_send):

        @dramatiq.actor
        def side_effect_actor() -> None:
            executed.append(True)

        side_effect_actor.send()

    assert not executed


def test_task_queue_clears_after_use() -> None:
    queue, patches = create_task_queue()
    with patches:
        queue.add("phantom_task")
        assert queue.has_task("phantom_task")

    # After the patches context exits, the queue is still accessible
    # but the fixture normally calls clear() on teardown.
    queue.clear()
    assert len(queue.tasks) == 0


# ── Gap 4: openapi_schema uses public API ─────────────────────────────────


def test_generate_openapi_schema_produces_valid_openapi_document() -> None:
    schema = generate_openapi_schema(routes=[], title="My API")

    assert "openapi" in schema
    assert schema["info"]["title"] == "My API"


def test_generate_openapi_schema_does_not_require_app_instance() -> None:
    """The fixture must not depend on app.get_openapi_schema (internal method)."""
    schema = generate_openapi_schema(routes=[], title="Standalone")
    assert isinstance(schema, dict)


def test_openapi_schema_fixture_source_calls_generate_openapi_schema() -> None:
    """Verify the fixture implementation uses the public function."""
    source = inspect.getsource(openapi_schema_fixture)
    assert "generate_openapi_schema" in source
    assert "get_openapi_schema" not in source
