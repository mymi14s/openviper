"""Unit tests for openviper/storage/base.py.

Covers:
- Storage abstract base contract
- FileSystemStorage: bytes / file-like / async-iterator / fallback content
- Security: path traversal, null bytes, empty name, escape-root detection
- Performance: UUID collision-resistance, unique-name format
- URL percent-encoding
- _DefaultStorage lazy proxy isolation
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.storage.base import (
    FileSystemStorage,
    Storage,
    _DefaultStorage,
    default_storage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fs(tmp_path: Path, **kwargs) -> FileSystemStorage:
    return FileSystemStorage(location=str(tmp_path), base_url="/media/", **kwargs)


# ---------------------------------------------------------------------------
# Storage abstract base
# ---------------------------------------------------------------------------


class TestStorageAbstract:
    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await Storage().save("x", b"")

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await Storage().delete("x")

    @pytest.mark.asyncio
    async def test_exists_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await Storage().exists("x")

    def test_url_not_implemented(self):
        with pytest.raises(NotImplementedError):
            Storage().url("x")

    @pytest.mark.asyncio
    async def test_size_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await Storage().size("x")

    def test_generate_unique_name_different_each_call(self):
        s = Storage()
        # pylint: disable=protected-access
        names = {s._generate_unique_name("photo.jpg") for _ in range(50)}
        assert len(names) == 50

    def test_generate_unique_name_preserves_extension(self):
        # pylint: disable=protected-access
        result = Storage()._generate_unique_name("archive.tar.gz")
        assert result.endswith(".gz")
        assert result != "archive.tar.gz"

    def test_generate_unique_name_full_uuid(self):
        """UUID suffix must be 32 hex chars (128-bit) for collision resistance."""
        # pylint: disable=protected-access
        result = Storage()._generate_unique_name("file.txt")
        # format: file_<32hex>.txt
        base_part = result[len("file_") : -len(".txt")]
        assert len(base_part) == 32
        assert all(c in "0123456789abcdef" for c in base_part)

    def test_generate_unique_name_no_extension(self):
        # pylint: disable=protected-access
        result = Storage()._generate_unique_name("Makefile")
        assert "Makefile_" in result
        assert result != "Makefile"


# ---------------------------------------------------------------------------
# FileSystemStorage._validate_name (security)
# ---------------------------------------------------------------------------


class TestValidateName:
    @pytest.fixture(autouse=True)
    def fs(self):
        # pylint: disable=attribute-defined-outside-init
        self._fs = FileSystemStorage(location="/tmp/media", base_url="/media/")

    def _v(self, name: str) -> str:
        # pylint: disable=protected-access
        return self._fs._validate_name(name)

    def test_simple_name_passes(self):
        assert self._v("photo.jpg") == "photo.jpg"

    def test_subdirectory_passes(self):
        assert self._v("uploads/2024/photo.jpg") == "uploads/2024/photo.jpg"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="empty"):
            self._v("")

    def test_null_byte_raises(self):
        with pytest.raises(ValueError, match="null bytes"):
            self._v("file\x00.txt")

    def test_traversal_dot_dot_stripped(self):
        result = self._v("../../etc/passwd")
        assert ".." not in result
        assert result == "etc/passwd"

    def test_traversal_absolute_path_stripped(self):
        result = self._v("/etc/shadow")
        assert result == "etc/shadow"

    def test_traversal_mixed_stripped(self):
        result = self._v("uploads/../../../secret")
        assert ".." not in result
        assert result in {"uploads/secret", "secret"}

    def test_resolves_to_empty_raises(self):
        with pytest.raises(ValueError):
            self._v("../../..")

    def test_long_component_truncated(self):
        long_name = "a" * 300 + ".txt"
        result = self._v(long_name)
        component = result.rsplit("/", maxsplit=1)[-1]
        assert len(component) <= 255

    def test_windows_backslash_normalised(self):
        result = self._v("uploads\\2024\\photo.jpg")
        assert "\\" not in result
        assert "photo.jpg" in result


# ---------------------------------------------------------------------------
# FileSystemStorage._full_path (path-escape guard)
# ---------------------------------------------------------------------------


class TestFullPath:
    def test_path_inside_root_ok(self, tmp_path):
        fs = make_fs(tmp_path)
        # pylint: disable=protected-access
        full = fs._full_path("uploads/photo.jpg")
        assert str(full).startswith(str(tmp_path.resolve()))

    def test_path_escape_raises(self, tmp_path):
        """_full_path is a defence-in-depth guard after _validate_name."""
        fs = FileSystemStorage(location=str(tmp_path), base_url="/media/")
        # Bypass _validate_name by calling _full_path directly.
        with pytest.raises(ValueError, match="escapes the storage root"):
            # pylint: disable=protected-access
            fs._full_path("../outside/secret.txt")


# ---------------------------------------------------------------------------
# FileSystemStorage.save — content types
# ---------------------------------------------------------------------------


class TestSaveContentTypes:
    @pytest.mark.asyncio
    async def test_save_bytes(self, tmp_path):
        fs = make_fs(tmp_path)
        name = await fs.save("hello.txt", b"hello world")
        assert (tmp_path / name).read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_save_bytes_crosses_chunk_boundary(self, tmp_path):
        fs = make_fs(tmp_path)
        data = b"x" * (1024 * 1024 * 3)  # 3 MB
        name = await fs.save("big.bin", data)
        assert (tmp_path / name).read_bytes() == data

    @pytest.mark.asyncio
    async def test_save_file_like_sync(self, tmp_path):
        fs = make_fs(tmp_path)
        name = await fs.save("file_like.txt", io.BytesIO(b"file content"))
        assert (tmp_path / name).read_bytes() == b"file content"

    @pytest.mark.asyncio
    async def test_save_file_like_async_read(self, tmp_path):
        """File-like objects with an async read() method are supported."""
        fs = make_fs(tmp_path)
        data = b"async read content"
        calls = iter([data, b""])

        # spec=io.RawIOBase prevents MagicMock from auto-creating __aiter__,
        # which would otherwise cause the async-iterator branch to fire first.
        mock_file = MagicMock(spec=io.RawIOBase)
        mock_file.read = AsyncMock(side_effect=lambda n: next(calls))

        name = await fs.save("async_file.txt", mock_file)
        assert (tmp_path / name).read_bytes() == data

    @pytest.mark.asyncio
    async def test_save_async_iterator(self, tmp_path):
        fs = make_fs(tmp_path)

        async def gen():
            yield b"chunk1"
            yield b"chunk2"
            yield b"chunk3"

        name = await fs.save("streamed.bin", gen())
        assert (tmp_path / name).read_bytes() == b"chunk1chunk2chunk3"

    @pytest.mark.asyncio
    async def test_save_fallback_bytearray(self, tmp_path):
        fs = make_fs(tmp_path)
        data = bytearray(b"bytearray data")
        name = await fs.save("fallback.bin", data)
        assert (tmp_path / name).read_bytes() == bytes(data)

    @pytest.mark.asyncio
    async def test_save_creates_subdirectory(self, tmp_path):
        fs = make_fs(tmp_path)
        await fs.save("deep/nested/dir/file.txt", b"nested")
        assert (tmp_path / "deep" / "nested" / "dir" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_save_returns_relative_name(self, tmp_path):
        fs = make_fs(tmp_path)
        name = await fs.save("photo.jpg", b"")
        assert not name.startswith("/")
        assert "photo" in name


# ---------------------------------------------------------------------------
# FileSystemStorage.save — path traversal rejected end-to-end
# ---------------------------------------------------------------------------


class TestSavePathTraversal:
    @pytest.mark.asyncio
    async def test_traversal_name_sanitised_to_root(self, tmp_path):
        """Path traversal components are stripped; the file lands inside the root."""
        fs = make_fs(tmp_path)
        name = await fs.save("../../etc/passwd", b"pwned")
        # The saved path must be inside tmp_path, not the real /etc/passwd.
        full = (tmp_path / name).resolve()
        assert str(full).startswith(str(tmp_path.resolve()))
        assert not (tmp_path / name).read_bytes() == b""  # file was actually written

    @pytest.mark.asyncio
    async def test_null_byte_in_name_raises(self, tmp_path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError):
            await fs.save("file\x00.txt", b"data")

    @pytest.mark.asyncio
    async def test_empty_name_raises(self, tmp_path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError):
            await fs.save("", b"data")


# ---------------------------------------------------------------------------
# FileSystemStorage.save — collision avoidance
# ---------------------------------------------------------------------------


class TestSaveCollision:
    @pytest.mark.asyncio
    async def test_unique_name_on_collision(self, tmp_path):
        fs = make_fs(tmp_path)
        name1 = await fs.save("file.txt", b"first")
        name2 = await fs.save("file.txt", b"second")
        assert name1 != name2
        assert (tmp_path / name1).exists()
        assert (tmp_path / name2).exists()

    @pytest.mark.asyncio
    async def test_collision_file_has_correct_content(self, tmp_path):
        fs = make_fs(tmp_path)
        await fs.save("img.png", b"original")
        name2 = await fs.save("img.png", b"duplicate")
        assert (tmp_path / name2).read_bytes() == b"duplicate"

    @pytest.mark.asyncio
    async def test_no_spurious_collision_for_distinct_names(self, tmp_path):
        fs = make_fs(tmp_path)
        n1 = await fs.save("a.txt", b"a")
        n2 = await fs.save("b.txt", b"b")
        assert n1 == "a.txt"
        assert n2 == "b.txt"


# ---------------------------------------------------------------------------
# FileSystemStorage — exists / delete / size
# ---------------------------------------------------------------------------


class TestExistsDeleteSize:
    @pytest.mark.asyncio
    async def test_exists_true(self, tmp_path):
        fs = make_fs(tmp_path)
        (tmp_path / "test.txt").write_bytes(b"data")
        assert await fs.exists("test.txt") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, tmp_path):
        assert await make_fs(tmp_path).exists("ghost.txt") is False

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, tmp_path):
        fs = make_fs(tmp_path)
        (tmp_path / "del.txt").write_bytes(b"bye")
        await fs.delete("del.txt")
        assert not (tmp_path / "del.txt").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_silent(self, tmp_path):
        await make_fs(tmp_path).delete("ghost.txt")  # must not raise

    @pytest.mark.asyncio
    async def test_size_returns_byte_count(self, tmp_path):
        fs = make_fs(tmp_path)
        content = b"hello world"
        (tmp_path / "sized.txt").write_bytes(content)
        assert await fs.size("sized.txt") == len(content)

    @pytest.mark.asyncio
    async def test_roundtrip_save_delete_exists(self, tmp_path):
        fs = make_fs(tmp_path)
        name = await fs.save("round.txt", b"trip")
        assert await fs.exists(name)
        await fs.delete(name)
        assert not await fs.exists(name)


# ---------------------------------------------------------------------------
# FileSystemStorage.url — percent-encoding
# ---------------------------------------------------------------------------


class TestUrl:
    def test_url_simple(self, tmp_path):
        assert make_fs(tmp_path).url("uploads/photo.jpg") == "/media/uploads/photo.jpg"

    def test_url_spaces_encoded(self, tmp_path):
        result = make_fs(tmp_path).url("my files/my photo.jpg")
        assert " " not in result
        assert "%20" in result

    def test_url_special_chars_encoded(self, tmp_path):
        result = make_fs(tmp_path).url("files/naïve café.txt")
        assert " " not in result

    def test_url_base_trailing_slash_normalised(self):
        fs = FileSystemStorage(location="/tmp", base_url="/media///")
        url = fs.url("file.txt")
        assert not url.startswith("/media///")
        assert url.startswith("/media")

    def test_url_deep_path(self, tmp_path):
        assert make_fs(tmp_path).url("a/b/c/d.jpg") == "/media/a/b/c/d.jpg"


# ---------------------------------------------------------------------------
# FileSystemStorage — settings fallback
# ---------------------------------------------------------------------------


class TestSettingsFallback:
    def test_location_falls_back_to_settings(self):
        loc = FileSystemStorage().location
        assert isinstance(loc, str) and loc

    def test_base_url_falls_back_to_settings(self):
        url = FileSystemStorage().base_url
        assert isinstance(url, str) and url

    def test_explicit_location_overrides_settings(self, tmp_path):
        fs = FileSystemStorage(location=str(tmp_path))
        assert fs.location == str(tmp_path)

    def test_explicit_base_url_overrides_settings(self):
        fs = FileSystemStorage(base_url="/files/")
        assert fs.base_url == "/files/"


# ---------------------------------------------------------------------------
# _DefaultStorage lazy proxy
# ---------------------------------------------------------------------------


class TestDefaultStorage:
    def test_lazy_creates_filesystem_storage(self):
        ds = _DefaultStorage()
        # pylint: disable=protected-access
        assert isinstance(ds._get_storage(), FileSystemStorage)

    def test_configure_sets_instance(self):
        ds = _DefaultStorage()
        fs = FileSystemStorage(location="/tmp", base_url="/media/")
        ds.configure(fs)
        # pylint: disable=protected-access
        assert ds._get_storage() is fs

    def test_proxy_delegates_url(self):
        ds = _DefaultStorage()
        ds.configure(FileSystemStorage(location="/tmp", base_url="/media/"))
        assert ds.url("photo.jpg") == "/media/photo.jpg"

    def test_instances_are_independent(self):
        """configure() on one _DefaultStorage must not pollute another."""
        ds1 = _DefaultStorage()
        ds2 = _DefaultStorage()
        custom = FileSystemStorage(location="/custom/")
        ds1.configure(custom)
        # ds2 must be lazily initialised independently.
        # pylint: disable=protected-access
        assert ds2._instance is None
        assert isinstance(ds2._get_storage(), FileSystemStorage)
        assert ds2._get_storage() is not custom

    def test_default_storage_module_level_is_proxy(self):
        assert isinstance(default_storage, _DefaultStorage)

    def test_getattr_proxy_exposes_url(self):
        ds = _DefaultStorage()
        assert hasattr(ds, "url")

    def test_repeated_get_storage_returns_same_instance(self):
        ds = _DefaultStorage()
        # pylint: disable=protected-access
        a = ds._get_storage()
        b = ds._get_storage()
        assert a is b


# ---------------------------------------------------------------------------
# Additional branch coverage
# ---------------------------------------------------------------------------


class TestMkdirAsyncRaceCondition:
    @pytest.mark.asyncio
    async def test_file_exists_error_is_swallowed(self, tmp_path):
        """_mkdir_async swallows FileExistsError (race condition guard, lines 185-187)."""

        storage = make_fs(tmp_path)
        with patch(
            "openviper.storage.base.aiofiles.os.makedirs",
            new=AsyncMock(side_effect=FileExistsError),
        ):
            # Must not raise
            await storage._mkdir_async(tmp_path / "subdir")


class TestLargeBytesSleep:
    @pytest.mark.asyncio
    async def test_asyncio_sleep_yielded_for_large_bytes(self, tmp_path):
        """asyncio.sleep(0) is yielded when large bytes cross 10-chunk boundary (line 226)."""

        storage = make_fs(tmp_path, chunk_size=1)
        # 10 bytes with chunk_size=1 → offset reaches 10 → 10 % 10 == 0 → sleep(0)
        content = b"a" * 10

        with patch("openviper.storage.base.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await storage.save("large.bin", content)

        mock_sleep.assert_called_with(0)


class TestFileLikeNonBytesChunk:
    @pytest.mark.asyncio
    async def test_bytearray_chunk_converted_to_bytes(self, tmp_path):
        """bytes(chunk) conversion fires when file-like read returns non-bytes (line 244)."""
        storage = make_fs(tmp_path)

        class _ByteArrayReader:
            def __init__(self, data: bytes):
                self._data = data
                self._pos = 0

            def read(self, n):
                chunk = self._data[self._pos : self._pos + n]
                self._pos += n
                if not chunk:
                    return bytearray()  # EOF as bytearray
                return bytearray(chunk)  # non-bytes so line 244 fires

        reader = _ByteArrayReader(b"hello world")
        name = await storage.save("test.bin", reader)
        # Verify the file was written correctly
        written = (tmp_path / name).read_bytes()
        assert written == b"hello world"
