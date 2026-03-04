import asyncio

import pytest

from tests.factories.app_factory import create_application
from tests.utils.test_client import OpenviperTestClient


@pytest.mark.asyncio
async def test_app_lifecycle_integration():
    app = create_application()

    @app.get("/")
    async def index():
        return "root"

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    async with OpenviperTestClient(app) as client:
        response = await client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"pong": True}


@pytest.mark.asyncio
async def test_app_error_integration():
    app = create_application(debug=False)

    @app.get("/")
    async def index():
        return "root"

    @app.get("/error")
    async def cause_error():
        raise ValueError("Server crash")

    async with OpenviperTestClient(app) as client:
        response = await client.get("/error")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}


@pytest.mark.asyncio
async def test_app_startup_shutdown_handlers():
    app = create_application()
    state = {"startup": False, "shutdown": False}

    @app.on_startup
    async def startup():
        state["startup"] = True

    @app.on_shutdown
    async def shutdown():
        state["shutdown"] = True

    # Simulate ASGI lifespan
    scope = {"type": "lifespan"}

    queue = asyncio.Queue()
    await queue.put({"type": "lifespan.startup"})

    async def receive():
        return await queue.get()

    async def send(message):
        if message["type"] == "lifespan.startup.complete":
            await queue.put({"type": "lifespan.shutdown"})
        elif message["type"] == "lifespan.shutdown.complete":
            pass

    # We need to run the app in a task to handle the lifespan
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.sleep(0.1)  # Give it time to process

    assert state["startup"] is True
    # Lifespan should have finished after shutdown
    await task
    assert state["shutdown"] is True
