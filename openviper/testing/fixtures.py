"""Core pytest fixtures for OpenViper TestKit."""

import contextlib
import dataclasses
import inspect
import typing as t
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import dramatiq
import pytest
import pytest_asyncio

if t.TYPE_CHECKING:
    import httpx

    from openviper.app import OpenViper
    from openviper.core.email.message import EmailMessageData
    from openviper.db.models import Model

import openviper.cache as cache_module
from openviper.cache.memory import InMemoryCache
from openviper.core.email import sender as email_sender
from openviper.db import events as db_events
from openviper.openapi.schema import generate_openapi_schema
from openviper.testing.auth import force_authenticate, with_permissions, with_roles
from openviper.testing.cli import build_cli_runner
from openviper.testing.client import OpenViperTestClient
from openviper.testing.database import (
    SessionDatabase,
    TestDatabase,
    build_session_database,
    build_test_database,
    database_context,
    session_database_context,
)
from openviper.testing.events import EventRecorder
from openviper.testing.factories import SuperuserFactory, UserFactory
from openviper.testing.mail import TestEmail
from openviper.testing.settings import (
    OpenViperTestConfig,
    PytestConfigProtocol,
    load_app,
    load_testing_config,
    override_openviper_settings,
)
from openviper.testing.snapshot import Snapshot
from openviper.testing.storage import uploaded_file as build_uploaded_file
from openviper.testing.tasks import EagerTaskRunner, TaskQueue


@dataclasses.dataclass(slots=True)
class TestUser:
    """Simple user-like object for auth helper fixtures."""

    __test__ = False

    id: int
    email: str
    is_staff: bool = False
    is_superuser: bool = False
    permissions: set[str] = dataclasses.field(default_factory=set)
    roles: set[str] = dataclasses.field(default_factory=set)

    @property
    def pk(self) -> int:
        return self.id


@pytest.fixture(scope="session")
def openviper_test_config(request: pytest.FixtureRequest) -> OpenViperTestConfig:
    return load_testing_config(t.cast("PytestConfigProtocol", request.config))


@pytest_asyncio.fixture
async def app(openviper_test_config: OpenViperTestConfig) -> AsyncIterator[OpenViper]:
    loaded_app = await load_app(openviper_test_config)
    await run_lifespan_event(loaded_app, "lifespan.startup")
    try:
        yield loaded_app
    finally:
        await run_lifespan_event(loaded_app, "lifespan.shutdown")


@pytest_asyncio.fixture
async def client(app: OpenViper) -> AsyncIterator[httpx.AsyncClient]:
    async with OpenViperTestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def db(openviper_test_config: OpenViperTestConfig) -> AsyncIterator[TestDatabase]:
    database = build_test_database(
        openviper_test_config.database_url,
        openviper_test_config.database_isolation,
        openviper_test_config.migrate,
    )
    async with database_context(database) as test_database:
        yield test_database


@pytest_asyncio.fixture
async def transactional_db(
    openviper_test_config: OpenViperTestConfig,
) -> AsyncIterator[TestDatabase]:
    database = build_test_database(
        openviper_test_config.database_url,
        "recreate",
        openviper_test_config.migrate,
    )
    async with database_context(database) as test_database:
        yield test_database


@pytest_asyncio.fixture
async def migrated_db(openviper_test_config: OpenViperTestConfig) -> AsyncIterator[TestDatabase]:
    database = build_test_database(
        openviper_test_config.database_url,
        openviper_test_config.database_isolation,
        migrate=True,
    )
    async with database_context(database) as test_database:
        yield test_database


@pytest_asyncio.fixture
async def isolated_db(openviper_test_config: OpenViperTestConfig) -> AsyncIterator[TestDatabase]:
    database = build_test_database(
        openviper_test_config.database_url,
        "recreate",
        migrate=True,
    )
    async with database_context(database) as test_database:
        yield test_database


@pytest_asyncio.fixture(scope="session")
async def setup_test_database(
    openviper_test_config: OpenViperTestConfig,
) -> AsyncIterator[SessionDatabase]:
    """Session-scoped database fixture. Migrates once, keeps engine alive."""
    session_db = build_session_database(
        openviper_test_config.database_url,
        openviper_test_config.database_isolation,
    )
    async with session_database_context(session_db) as database:
        yield database


@pytest.fixture
def override_settings() -> Iterator[Callable[..., object]]:
    contexts: list[object] = []

    def apply_override(**overrides: object) -> object:
        context = override_openviper_settings(**overrides)
        contexts.append(context)
        return context.__enter__()

    try:
        yield apply_override
    finally:
        for context in reversed(contexts):
            context.__exit__(None, None, None)


def create_mailoutbox() -> tuple[list[TestEmail], contextlib.ExitStack]:
    """Return ``(outbox, patches)``. Patches ``send_now`` into *outbox*
    and suppresses background delivery."""
    outbox: list[TestEmail] = []

    async def capturing_send(data: EmailMessageData) -> None:
        outbox.append(
            TestEmail(
                subject=data.subject,
                to=list(data.recipients),
                body=data.text or data.html or "",
                sender=data.sender,
            )
        )

    patches = contextlib.ExitStack()
    patches.enter_context(patch.object(email_sender, "send_now", capturing_send))
    patches.enter_context(patch("openviper.core.email.queue.worker_available", return_value=False))
    return outbox, patches


@pytest.fixture
def mailoutbox() -> Iterator[list[TestEmail]]:
    """Capture outgoing emails into a list. Suppresses background delivery."""
    outbox, patches = create_mailoutbox()
    with patches:
        yield outbox


@pytest.fixture
def event_recorder() -> Iterator[EventRecorder]:
    """Record model lifecycle events dispatched by the ORM."""
    recorder, patches = create_event_recorder()
    with patches:
        yield recorder
    recorder.clear()


def create_event_recorder() -> tuple[EventRecorder, contextlib.ExitStack]:
    """Return ``(recorder, patches)``. Patches dispatch to intercept model lifecycle events."""
    recorder = EventRecorder()
    original = db_events.dispatch_decorator_handlers

    def capturing_dispatch(
        model_path: str, event_name: str, objs: object, **kwargs: object
    ) -> None:
        recorder.record(f"{model_path}.{event_name}", **kwargs)
        original(model_path, event_name, objs, **kwargs)

    patches = contextlib.ExitStack()
    patches.enter_context(
        patch("openviper.db.models.dispatch_decorator_handlers", capturing_dispatch)
    )
    return recorder, patches


@pytest.fixture
def task_queue() -> Iterator[TaskQueue]:
    """Capture Dramatiq tasks into a queue without enqueuing to the broker."""
    queue, patches = create_task_queue()
    with patches:
        yield queue
    queue.clear()


def create_task_queue() -> tuple[TaskQueue, contextlib.ExitStack]:
    """Return ``(queue, patches)``. Patches ``Actor.send_with_options`` to capture tasks."""
    queue = TaskQueue()

    def capturing_send(self: dramatiq.Actor, *, args: tuple, kwargs: dict, **opts: object) -> None:
        queue.add(self.actor_name, *args, **kwargs)

    patches = contextlib.ExitStack()
    patches.enter_context(patch.object(dramatiq.Actor, "send_with_options", capturing_send))
    return queue, patches


@pytest.fixture
def task_runner() -> EagerTaskRunner:
    return EagerTaskRunner()


@pytest.fixture
def disable_tasks() -> Iterator[TaskQueue]:
    """Prevent any Dramatiq task from being enqueued during the test."""
    queue, patches = create_task_queue()
    with patches:
        yield queue


@pytest.fixture
def cache() -> Iterator[InMemoryCache]:
    """Isolated in-memory cache replacing the global default backend for the test."""
    instance, restore = setup_test_cache()
    try:
        yield instance
    finally:
        restore()


def setup_test_cache() -> tuple[InMemoryCache, Callable[[], None]]:
    """Return ``(instance, restore)``. Wires an ``InMemoryCache`` as the default backend."""
    instance = InMemoryCache()
    previous = dict(cache_module.cache_instances)
    cache_module.cache_instances.clear()
    cache_module.cache_instances["default"] = instance

    def restore() -> None:
        cache_module.cache_instances.clear()
        cache_module.cache_instances.update(previous)

    return instance, restore


@pytest.fixture
def clear_cache(cache: InMemoryCache) -> Callable[[], t.Awaitable[None]]:
    return cache.clear


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Path:
    storage_path = tmp_path / "storage"
    storage_path.mkdir()
    return storage_path


@pytest.fixture
def uploaded_file() -> Callable[[str, bytes, str], object]:
    return build_uploaded_file


@pytest.fixture
def user() -> TestUser:
    return TestUser(id=1, email="user@example.com")


@pytest.fixture
def admin_user() -> TestUser:
    admin = TestUser(
        id=2,
        email="admin@example.com",
        is_staff=True,
        is_superuser=True,
    )
    with_roles(admin, {"admin"})
    with_permissions(admin, {"admin.access"})
    return admin


@pytest.fixture
def user_factory() -> Callable[..., TestUser]:
    counter = 0

    def create_user(**overrides: object) -> TestUser:
        nonlocal counter
        counter += 1
        return TestUser(
            id=t.cast("int", overrides.get("id", counter)),
            email=t.cast("str", overrides.get("email", f"user{counter}@example.com")),
            is_staff=t.cast("bool", overrides.get("is_staff", False)),
            is_superuser=t.cast("bool", overrides.get("is_superuser", False)),
        )

    return create_user


@pytest_asyncio.fixture
async def auth_client(client: httpx.AsyncClient, user: TestUser) -> httpx.AsyncClient:
    """JWT-authenticated client using a stub user (no DB record)."""
    return force_authenticate(client, user)


@pytest_asyncio.fixture
async def admin_client(client: httpx.AsyncClient, admin_user: TestUser) -> httpx.AsyncClient:
    """JWT-authenticated client using a stub admin user (no DB record)."""
    return force_authenticate(client, admin_user)


@pytest_asyncio.fixture
async def db_user(db: TestDatabase) -> Model:
    """Create and return a real User record in the test database."""
    return await UserFactory.create()


@pytest_asyncio.fixture
async def db_admin_user(db: TestDatabase) -> Model:
    """Create and return a real superuser record in the test database."""
    return await SuperuserFactory.create()


@pytest_asyncio.fixture
async def authenticated_client(
    client: httpx.AsyncClient,
    db_user: Model,
) -> httpx.AsyncClient:
    """JWT-authenticated client backed by a real DB user record."""
    return force_authenticate(client, db_user)


@pytest_asyncio.fixture
async def admin_authenticated_client(
    client: httpx.AsyncClient,
    db_admin_user: Model,
) -> httpx.AsyncClient:
    """JWT-authenticated client backed by a real DB superuser record."""
    return force_authenticate(client, db_admin_user)


@pytest.fixture
def cli_runner() -> object:
    return build_cli_runner()


@pytest.fixture
def openapi_schema(app: OpenViper) -> dict[str, object]:
    """Return the app's OpenAPI schema."""
    return generate_openapi_schema(
        routes=app.router.routes,
        title=app.title,
    )


@pytest.fixture
def snapshot(tmp_path: Path) -> Snapshot:
    return Snapshot(tmp_path / "snapshots")


async def run_lifespan_event(app: OpenViper, event_type: str) -> None:
    if event_type == "lifespan.startup":
        app._get_middleware_app()
        app.get_openapi_schema()
        await app._call_installed_app_ready_hooks()
        handlers = app._startup_handlers
    elif event_type == "lifespan.shutdown":
        handlers = app._shutdown_handlers
    else:
        raise RuntimeError(f"Unsupported OpenViper lifespan event {event_type!r}.")

    for handler in handlers:
        result = handler()
        if inspect.isawaitable(result):
            await result
