from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

import openviper
from openviper.storage import FileSystemStorage, default_storage


@pytest.fixture
def storage():
    # Use a local test_media directory
    tmp_media = Path("test_media")
    if tmp_media.exists():
        shutil.rmtree(tmp_media)
    tmp_media.mkdir()

    yield FileSystemStorage(location=str(tmp_media), base_url="/test-media/")

    # Cleanup
    if tmp_media.exists():
        shutil.rmtree(tmp_media)


@pytest.mark.asyncio
async def test_lazy_getattr_loads_known_subpackage():
    """openviper.__getattr__ lazily imports a known subpackage and caches it."""

    tasks_module = openviper.__getattr__("tasks")
    assert tasks_module is openviper.tasks
    assert "tasks" in openviper.__dict__


@pytest.mark.asyncio
async def test_storage_save_and_exists(storage):
    content = b"hello storage"
    path = await storage.save("test.txt", content)

    assert path == "test.txt"
    assert await storage.exists(path)

    # Check full file content
    full_path = Path(storage.location) / path
    assert full_path.read_bytes() == content


@pytest.mark.asyncio
async def test_storage_collision(storage):
    content1 = b"file 1"
    content2 = b"file 2"

    path1 = await storage.save("duplicate.txt", content1)
    path2 = await storage.save("duplicate.txt", content2)

    assert path1 == "duplicate.txt"
    assert path2 != "duplicate.txt"
    assert "duplicate_" in path2

    assert await storage.exists(path1)
    assert await storage.exists(path2)

    assert (Path(storage.location) / path1).read_bytes() == content1
    assert (Path(storage.location) / path2).read_bytes() == content2


@pytest.mark.asyncio
async def test_storage_delete(storage):
    path = await storage.save("delete_me.txt", b"gone")
    assert await storage.exists(path)

    await storage.delete(path)
    assert not await storage.exists(path)


def test_storage_url(storage):
    assert storage.url("photo.jpg") == "/test-media/photo.jpg"


@pytest.mark.asyncio
async def test_setup_runs_without_error():
    """openviper.setup() calls settings._setup() without raising."""

    # Should not raise even when called repeatedly (force=False is idempotent)
    openviper.setup()
    openviper.setup()


@pytest.mark.asyncio
async def test_storage_size(storage):
    content = b"some data"
    path = await storage.save("size.txt", content)
    assert await storage.size(path) == len(content)


@pytest.mark.asyncio
async def test_storage_file_like_save(storage):
    bio = io.BytesIO(b"streamed content")
    path = await storage.save("stream.txt", bio)
    assert (Path(storage.location) / path).read_bytes() == b"streamed content"


def test_default_storage_proxy():
    # default_storage should be a proxy
    assert hasattr(default_storage, "save")
    assert hasattr(default_storage, "delete")
    assert hasattr(default_storage, "url")


@pytest.mark.asyncio
async def test_storage_save_with_async_read(storage):
    content_bytes = b"async content data"

    class AsyncReadContent:
        def read(self):
            # Returns a coroutine (has __await__)
            async def _read():
                return content_bytes

            return _read()

    path = await storage.save("async_test.txt", AsyncReadContent())
    assert path == "async_test.txt"
    assert await storage.exists(path)
    assert (Path(storage.location) / path).read_bytes() == content_bytes
