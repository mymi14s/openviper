"""Integration tests for openviper.storage.base (FileSystemStorage, Storage)."""

from __future__ import annotations

import io

import pytest

from openviper.storage.base import FileSystemStorage, Storage, _DefaultStorage, default_storage

# ---------------------------------------------------------------------------
# Storage abstract base
# ---------------------------------------------------------------------------


class TestStorageAbstract:
    @pytest.mark.asyncio
    async def test_save_raises_not_implemented(self):
        s = Storage()
        with pytest.raises(NotImplementedError):
            await s.save("file.txt", b"data")

    @pytest.mark.asyncio
    async def test_delete_raises_not_implemented(self):
        s = Storage()
        with pytest.raises(NotImplementedError):
            await s.delete("file.txt")

    @pytest.mark.asyncio
    async def test_exists_raises_not_implemented(self):
        s = Storage()
        with pytest.raises(NotImplementedError):
            await s.exists("file.txt")

    def test_url_raises_not_implemented(self):
        s = Storage()
        with pytest.raises(NotImplementedError):
            s.url("file.txt")

    @pytest.mark.asyncio
    async def test_size_raises_not_implemented(self):
        s = Storage()
        with pytest.raises(NotImplementedError):
            await s.size("file.txt")

    def test_generate_unique_name_with_ext(self):
        s = Storage()
        result = s._generate_unique_name("photo.jpg")
        assert result.endswith(".jpg")
        assert result != "photo.jpg"  # Has UUID suffix

    def test_generate_unique_name_without_ext(self):
        s = Storage()
        result = s._generate_unique_name("noextension")
        assert "noextension" in result


# ---------------------------------------------------------------------------
# FileSystemStorage
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_storage(tmp_path):
    return FileSystemStorage(location=str(tmp_path), base_url="/media/")


class TestFileSystemStorage:
    @pytest.mark.asyncio
    async def test_save_bytes(self, tmp_storage):
        path = await tmp_storage.save("test.txt", b"hello storage")
        assert path == "test.txt"
        # Verify file exists
        assert await tmp_storage.exists("test.txt")

    @pytest.mark.asyncio
    async def test_save_file_like_object(self, tmp_storage):
        content = io.BytesIO(b"file content")
        await tmp_storage.save("doc.txt", content)
        assert await tmp_storage.exists("doc.txt")

    @pytest.mark.asyncio
    async def test_save_duplicate_renames(self, tmp_storage):
        await tmp_storage.save("dup.txt", b"first")
        path2 = await tmp_storage.save("dup.txt", b"second")
        # Second save should get a different name
        assert path2 != "dup.txt"
        assert await tmp_storage.exists(path2)

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, tmp_storage):
        await tmp_storage.save("to_delete.txt", b"bye")
        await tmp_storage.delete("to_delete.txt")
        assert not await tmp_storage.exists("to_delete.txt")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file_no_error(self, tmp_storage):
        # Should not raise
        await tmp_storage.delete("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_exists_false_for_missing(self, tmp_storage):
        assert not await tmp_storage.exists("not_here.txt")

    @pytest.mark.asyncio
    async def test_exists_true_after_save(self, tmp_storage):
        await tmp_storage.save("present.txt", b"data")
        assert await tmp_storage.exists("present.txt")

    @pytest.mark.asyncio
    async def test_size_returns_correct_size(self, tmp_storage):
        content = b"12345"
        await tmp_storage.save("sized.txt", content)
        size = await tmp_storage.size("sized.txt")
        assert size == 5

    def test_url_returns_prefixed_path(self, tmp_storage):
        url = tmp_storage.url("image.png")
        assert url == "/media/image.png"

    def test_url_strips_trailing_slash(self, tmp_storage):
        s = FileSystemStorage(base_url="/media/")
        url = s.url("img.png")
        assert not url.startswith("/media//")

    def test_location_from_init(self, tmp_storage, tmp_path):
        assert tmp_storage.location == str(tmp_path)

    def test_location_from_settings_when_none(self):
        s = FileSystemStorage()
        # Should return settings.MEDIA_ROOT or default
        loc = s.location
        assert isinstance(loc, str)

    def test_base_url_from_init(self, tmp_storage):
        assert tmp_storage.base_url == "/media/"

    def test_base_url_from_settings_when_none(self):
        s = FileSystemStorage()
        url = s.base_url
        assert isinstance(url, str)

    @pytest.mark.asyncio
    async def test_save_creates_nested_dirs(self, tmp_storage):
        await tmp_storage.save("uploads/images/photo.jpg", b"img data")
        assert await tmp_storage.exists("uploads/images/photo.jpg")

    @pytest.mark.asyncio
    async def test_save_non_bytes_coerced(self, tmp_storage):
        """Test save with content that requires bytes() coercion."""

        class FakeContent:
            def __bytes__(self):
                return b"fake content"

        content = FakeContent()
        path = await tmp_storage.save("fake.bin", content)
        assert await tmp_storage.exists(path)


# ---------------------------------------------------------------------------
# _DefaultStorage proxy
# ---------------------------------------------------------------------------


class TestDefaultStorage:
    def test_default_storage_is_lazy_proxy(self):
        assert isinstance(default_storage, _DefaultStorage)

    def test_configure_overrides_backend(self, tmp_path):
        proxy = _DefaultStorage()
        custom = FileSystemStorage(location=str(tmp_path))
        proxy.configure(custom)
        # Accessing an attribute should delegate to the custom backend
        assert proxy.location == str(tmp_path)

    def test_getattr_delegates(self):
        proxy = _DefaultStorage()
        # url is a method on FileSystemStorage
        assert hasattr(proxy, "url")
