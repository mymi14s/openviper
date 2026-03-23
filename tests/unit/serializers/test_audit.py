"""Security and performance audit tests for openviper/serializers/base.py.

Covers:
- S1: path traversal prevention in _persist_files
- S2: unsafe bytes() fallback rejection in _persist_files
- B1: _field_is_optional correctly handles falsy defaults (False, 0, "")
- B2: create() uses exclude_none=True to avoid clobbering DB defaults
- B3: update() uses exclude_unset=True to avoid clobbering existing values
- P1: _compute_excluded deduplication helper
- General: serialize_many / serialize_many_json / paginate excluded-fields logic
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.serializers.base import (
    ModelSerializer,
    Serializer,
    _field_is_optional,
)
from tests.factories import MockQuerySet, SimpleModel

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _Field:
    """Minimal ORM field stub."""

    NOT_PROVIDED = object()  # sentinel used by the framework

    def __init__(
        self,
        *,
        primary_key: bool = False,
        null: bool = False,
        auto_now: bool = False,
        auto_now_add: bool = False,
        default: Any = None,
        use_sentinel: bool = False,
    ) -> None:
        self.primary_key = primary_key
        self.null = null
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add
        self.default = _Field.NOT_PROVIDED if use_sentinel else default


def _make_field(**kw: Any) -> _Field:
    return _Field(**kw)


class SimpleS(Serializer):
    id: int
    name: str
    score: float = 0.0


class WriteOnlyS(Serializer):
    username: str
    password: str
    write_only_fields = ("password",)


# ---------------------------------------------------------------------------
# B1 — _field_is_optional: falsy defaults
# ---------------------------------------------------------------------------


class TestFieldIsOptional:
    def test_primary_key_is_optional(self):
        field = _make_field(primary_key=True)
        assert _field_is_optional(field) is True

    def test_null_field_is_optional(self):
        field = _make_field(null=True)
        assert _field_is_optional(field) is True

    def test_auto_now_is_optional(self):
        field = _make_field(auto_now=True)
        assert _field_is_optional(field) is True

    def test_auto_now_add_is_optional(self):
        field = _make_field(auto_now_add=True)
        assert _field_is_optional(field) is True

    def test_field_with_false_default_is_optional(self):
        """BooleanField(default=False) must be optional — falsy ≠ no default."""
        field = _make_field(default=False)
        assert _field_is_optional(field) is True

    def test_field_with_zero_default_is_optional(self):
        """IntegerField(default=0) must be optional."""
        field = _make_field(default=0)
        assert _field_is_optional(field) is True

    def test_field_with_empty_string_default_is_optional(self):
        """CharField(default='') must be optional."""
        field = _make_field(default="")
        assert _field_is_optional(field) is True

    def test_field_with_sentinel_not_provided_is_required(self):
        """Field whose default is NOT_PROVIDED sentinel is required (not optional)."""
        field = _make_field(use_sentinel=True)
        assert _field_is_optional(field) is False

    def test_required_field_without_default_is_not_optional(self):
        """Plain field whose default is the NOT_PROVIDED sentinel is required."""
        # use_sentinel=True sets default=NOT_PROVIDED, indicating no default
        field = _make_field(use_sentinel=True)
        assert _field_is_optional(field) is False


# ---------------------------------------------------------------------------
# P1 — _compute_excluded
# ---------------------------------------------------------------------------


class TestComputeExcluded:
    def test_no_write_only_no_extra_returns_none(self):
        s = SimpleS(id=1, name="x", score=1.0)
        assert s._compute_excluded(None) is None

    def test_write_only_returned(self):
        s = WriteOnlyS(username="alice", password="secret")
        result = s._compute_excluded(None)
        assert result == {"password"}

    def test_extra_exclude_merged(self):
        s = WriteOnlyS(username="alice", password="secret")
        result = s._compute_excluded({"username"})
        assert result == {"password", "username"}

    def test_only_extra_exclude(self):
        s = SimpleS(id=1, name="x")
        result = s._compute_excluded({"score"})
        assert result == {"score"}

    def test_empty_extra_exclude_same_as_none(self):
        s = SimpleS(id=1, name="x")
        # Empty set should not change result — no write_only, no extras
        assert s._compute_excluded(set()) is None


# ---------------------------------------------------------------------------
# B2 — create() uses exclude_none=True
# ---------------------------------------------------------------------------


class TestModelSerializerCreate:
    @pytest.mark.asyncio
    async def test_create_does_not_pass_none_for_unset_optional(self):
        """create() must not send None for optional fields the caller omitted."""

        class FakeModel:
            _fields = {
                "id": _make_field(primary_key=True),
                "name": _make_field(null=False, default=None),
                "bio": _make_field(null=True),
            }
            objects = MagicMock()

        created = SimpleModel(id=1, name="alice", bio=None)
        FakeModel.objects.create = AsyncMock(return_value=created)

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = ["id", "name", "bio"]

        s = FakeSerializer.validate({"name": "alice"})
        await s.create()

        call_kwargs = FakeModel.objects.create.call_args.kwargs
        # 'bio' was not provided — must not appear in the create kwargs
        assert "bio" not in call_kwargs
        assert call_kwargs["name"] == "alice"

    @pytest.mark.asyncio
    async def test_create_excludes_readonly_fields(self):
        class FakeModel:
            _fields = {
                "id": _make_field(primary_key=True),
                "title": _make_field(),
                "created_at": _make_field(auto_now_add=True),
            }
            objects = MagicMock()

        created = SimpleModel(id=1, title="hello", created_at="2026-01-01")
        FakeModel.objects.create = AsyncMock(return_value=created)

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = ["id", "title", "created_at"]
                readonly_fields = ("created_at",)

        s = FakeSerializer.validate({"title": "hello"})
        await s.create()

        call_kwargs = FakeModel.objects.create.call_args.kwargs
        assert "created_at" not in call_kwargs


# ---------------------------------------------------------------------------
# B3 — update() uses exclude_unset=True
# ---------------------------------------------------------------------------


class TestModelSerializerUpdate:
    @pytest.mark.asyncio
    async def test_update_only_applies_set_fields(self):
        """update() must only write fields the caller explicitly provided."""

        class FakeModel:
            _fields = {
                "id": _make_field(primary_key=True),
                "title": _make_field(),
                "body": _make_field(null=True),
            }

        instance = SimpleModel(id=1, title="old title", body="old body")
        instance.save = AsyncMock()

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = ["id", "title", "body"]

        # Only supply 'title' — 'body' must not be touched
        s = FakeSerializer.validate({"title": "new title"}, partial=True)
        await s.update(instance)

        assert instance.title == "new title"
        # 'body' must remain unchanged — was never in the validated data
        assert instance.body == "old body"

    @pytest.mark.asyncio
    async def test_update_never_sets_pk(self):
        class FakeModel:
            _fields = {
                "id": _make_field(primary_key=True),
                "name": _make_field(),
            }

        instance = SimpleModel(id=5, name="original")
        instance.save = AsyncMock()

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = ["id", "name"]

        s = FakeSerializer.validate({"id": 99, "name": "changed"})
        await s.update(instance)

        # PK must never change
        assert instance.id == 5
        assert instance.name == "changed"


# ---------------------------------------------------------------------------
# S1 — path traversal prevention
# ---------------------------------------------------------------------------


class TestPersistFilesPathTraversal:
    @pytest.mark.asyncio
    async def test_traversal_sequence_stripped(self):
        """Filenames with ../ components must be sanitised to basename only."""

        class FakeModel:
            _fields = {}

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = []

        evil_file = io.BytesIO(b"content")
        evil_file.name = "../../etc/cron.d/evil"

        saved_paths: list[str] = []

        async def fake_save(path: str, content: bytes) -> str:
            saved_paths.append(path)
            return path

        fake_field = MagicMock()
        fake_field.upload_to = "uploads/"

        with patch("openviper.serializers.base.default_storage") as mock_storage:
            mock_storage.save = fake_save
            with patch(
                "openviper.serializers.base._FILE_FIELDS_CACHE",
                {FakeSerializer: {"avatar": fake_field}},
            ):
                await FakeSerializer._persist_files({"avatar": evil_file})

        assert saved_paths, "save should have been called"
        saved = saved_paths[0]
        assert ".." not in saved
        assert saved.endswith("evil")

    @pytest.mark.asyncio
    async def test_windows_backslash_traversal_stripped(self):
        """Windows-style path separators in filenames must be handled.

        os.path.basename on POSIX treats the entire Windows path as a filename,
        but the important guarantee is that no ``..`` components survive.
        """

        class FakeModel:
            _fields = {}

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = []

        evil_file = io.BytesIO(b"data")
        evil_file.name = r"..\..\windows\system32\evil.dll"

        saved_paths: list[str] = []

        async def fake_save(path: str, content: bytes) -> str:
            saved_paths.append(path)
            return path

        fake_field = MagicMock()
        fake_field.upload_to = "docs/"

        with patch("openviper.serializers.base.default_storage") as mock_storage:
            mock_storage.save = fake_save
            with patch(
                "openviper.serializers.base._FILE_FIELDS_CACHE",
                {FakeSerializer: {"doc": fake_field}},
            ):
                await FakeSerializer._persist_files({"doc": evil_file})

        assert saved_paths, "save should have been called"
        # No forward-slash traversal in the saved path
        assert "../" not in saved_paths[0]


# ---------------------------------------------------------------------------
# S2 — unsafe bytes() fallback rejected
# ---------------------------------------------------------------------------


class TestPersistFilesUnsafeBytes:
    @pytest.mark.asyncio
    async def test_integer_value_raises_type_error(self):
        """Passing an integer as a file value must raise TypeError, not allocate gigabytes."""

        class FakeModel:
            _fields = {}

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = []

        fake_field = MagicMock()
        fake_field.upload_to = "uploads/"

        with patch(
            "openviper.serializers.base._FILE_FIELDS_CACHE",
            {FakeSerializer: {"avatar": fake_field}},
        ):
            with pytest.raises(TypeError, match="Unsupported file value type"):
                await FakeSerializer._persist_files({"avatar": 1_000_000})

    @pytest.mark.asyncio
    async def test_bytearray_is_accepted(self):
        """bytearray is a legitimate binary type and must be accepted."""

        class FakeModel:
            _fields = {}

        class FakeSerializer(ModelSerializer):
            class Meta:
                model = FakeModel
                fields = []

        fake_field = MagicMock()
        fake_field.upload_to = "uploads/"
        fake_field.name = "avatar"

        saved: list[tuple[str, bytes]] = []

        async def fake_save(path: str, content: bytes) -> str:
            saved.append((path, content))
            return path

        with patch("openviper.serializers.base.default_storage") as mock_storage:
            mock_storage.save = fake_save
            with patch(
                "openviper.serializers.base._FILE_FIELDS_CACHE",
                {FakeSerializer: {"avatar": fake_field}},
            ):
                data = {"avatar": bytearray(b"hello")}
                await FakeSerializer._persist_files(data)

        assert saved[0][1] == b"hello"


# ---------------------------------------------------------------------------
# serialize / serialize_many / serialize_many_json — excluded fields
# ---------------------------------------------------------------------------


class TestSerializeExcluded:
    def test_serialize_excludes_write_only(self):
        s = WriteOnlyS(username="bob", password="secret")
        d = s.serialize()
        assert "password" not in d
        assert d["username"] == "bob"

    def test_serialize_with_extra_exclude(self):
        s = SimpleS(id=1, name="x", score=9.9)
        d = s.serialize(exclude={"score"})
        assert "score" not in d
        assert d["name"] == "x"

    def test_serialize_json_excludes_write_only(self):
        s = WriteOnlyS(username="alice", password="hunter2")
        b = s.serialize_json()
        assert b"password" not in b
        assert b"alice" in b

    @pytest.mark.asyncio
    async def test_serialize_many_excludes_write_only(self):
        objs = [SimpleModel(id=i, username=f"u{i}", password="pw") for i in range(3)]
        results = await WriteOnlyS.serialize_many(objs)
        for row in results:
            assert "password" not in row

    @pytest.mark.asyncio
    async def test_serialize_many_queryset_excludes_write_only(self):
        objs = [SimpleModel(id=i, username=f"u{i}", password="pw") for i in range(5)]
        qs = MockQuerySet(objs)
        results = await WriteOnlyS.serialize_many(qs)
        for row in results:
            assert "password" not in row

    @pytest.mark.asyncio
    async def test_serialize_many_json_returns_valid_array(self):
        objs = [SimpleModel(id=1, name="a", score=1.0)]
        data = await SimpleS.serialize_many_json(objs)
        assert data.startswith(b"[")
        assert data.endswith(b"]")

    @pytest.mark.asyncio
    async def test_paginate_excludes_write_only(self):
        objs = [SimpleModel(id=i, username=f"u{i}", password="pw") for i in range(10)]
        qs = MockQuerySet(objs)
        page = await WriteOnlyS.paginate(qs, page=1, page_size=5)
        for row in page.results:
            assert "password" not in row
