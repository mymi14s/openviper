"""Integration tests for ModelSerializer CRUD methods (create/update/save)
and the serialize_json / serialize_many_json / PaginatedSerializer path.

These cover the previously uncovered lines 222-225, 237-242, 480-548.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.exceptions import DoesNotExist, ValidationError
from openviper.serializers.base import (
    ModelSerializer,
    PaginatedSerializer,
    Serializer,
)

# ---------------------------------------------------------------------------
# Helpers — minimal Model stub
# ---------------------------------------------------------------------------


def _make_model_stub(name="Post", fields=None):
    """Return a minimal model class with _fields and a mock objects manager."""
    if fields is None:
        fields = {
            "id": _make_field("AutoField", primary_key=True),
            "title": _make_field("CharField"),
        }
    objects = MagicMock()
    model = type(name, (), {"_fields": fields, "objects": objects})
    return model


def _make_field(cls_name, *, primary_key=False, null=False, default=None):
    f = MagicMock()
    f.__class__.__name__ = cls_name
    f.primary_key = primary_key
    f.null = null
    f.default = default
    f.auto_now = False
    f.auto_now_add = False
    return f


# ---------------------------------------------------------------------------
# serialize_json  (lines 222-225)
# ---------------------------------------------------------------------------


class WriteonlySerializer(Serializer):
    password: str
    token: str

    write_only_fields = ("token",)


def test_serialize_json_returns_bytes():
    s = WriteonlySerializer(password="secret", token="abc123")
    result = s.serialize_json()
    assert isinstance(result, bytes)
    import json

    data = json.loads(result)
    assert "password" in data
    assert "token" not in data  # write-only excluded


def test_serialize_json_with_extra_exclude():
    s = WriteonlySerializer(password="secret", token="abc123")
    result = s.serialize_json(exclude={"password"})
    import json

    data = json.loads(result)
    assert "password" not in data
    assert "token" not in data


# ---------------------------------------------------------------------------
# serialize_many_json  (lines 237-242)
# ---------------------------------------------------------------------------


class SimpleSerial(Serializer):
    id: int
    name: str


def test_serialize_many_json_returns_json_array():
    from types import SimpleNamespace

    objs = [SimpleNamespace(id=1, name="alice"), SimpleNamespace(id=2, name="bob")]
    result = SimpleSerial.serialize_many_json(objs)
    import json

    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["name"] == "alice"


def test_serialize_many_json_with_write_only_excluded():
    class SecureSerial(Serializer):
        id: int
        secret: str
        write_only_fields = ("secret",)

    objs = [MagicMock(id=1, secret="s1"), MagicMock(id=2, secret="s2")]
    result = SecureSerial.serialize_many_json(objs)
    import json

    data = json.loads(result)
    for item in data:
        assert "secret" not in item


# ---------------------------------------------------------------------------
# ModelSerializer.create  (lines 480-492)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_serializer_create_calls_objects_create():
    Model = _make_model_stub()

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title"]
            read_only_fields = ()

    post_created = MagicMock(id=1, title="Hello")
    Model.objects.create = AsyncMock(return_value=post_created)

    ser = PostSerializer.validate({"title": "Hello"})
    result = await ser.create()
    Model.objects.create.assert_called_once()
    assert result.title == "Hello"


@pytest.mark.asyncio
async def test_model_serializer_create_strips_pk_when_none():
    """id=None should be stripped before calling objects.create."""
    Model = _make_model_stub()

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title"]

    post = MagicMock(id=99, title="No PK")
    Model.objects.create = AsyncMock(return_value=post)

    ser = PostSerializer.validate({"title": "No PK"})
    await ser.create()
    call_kwargs = Model.objects.create.call_args.kwargs
    assert "id" not in call_kwargs


# ---------------------------------------------------------------------------
# ModelSerializer.update  (lines 494-511)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_serializer_update_sets_attrs_and_calls_save():
    Model = _make_model_stub()

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title"]
            read_only_fields = ()

    instance = MagicMock()
    instance.save = AsyncMock()

    ser = PostSerializer.validate({"title": "Updated"})
    await ser.update(instance)
    assert instance.title == "Updated"
    instance.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_serializer_update_strips_read_only_fields():
    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "title": _make_field("CharField"),
            "slug": _make_field("SlugField"),
        }
    )

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title", "slug"]
            read_only_fields = ("slug",)

    instance = MagicMock()
    instance.save = AsyncMock()

    ser = PostSerializer.validate({"title": "T", "slug": "t"})
    await ser.update(instance)
    # slug is read-only, should not be set
    assert not hasattr(instance, "slug") or instance.slug != "t"


# ---------------------------------------------------------------------------
# ModelSerializer.save  (lines 513-548)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_serializer_save_with_explicit_instance_calls_update():
    Model = _make_model_stub()

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title"]

    instance = MagicMock(id=5, title="old")
    instance.save = AsyncMock()
    instance.__dict__.update({"id": 5, "title": "Updated"})

    ser = PostSerializer.validate({"title": "Updated"})

    with patch.object(
        PostSerializer,
        "update",
        new=AsyncMock(return_value=instance),
    ) as mock_update:
        result = await ser.save(instance=instance)

    mock_update.assert_awaited_once_with(instance)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_model_serializer_save_creates_when_no_pk():
    Model = _make_model_stub()

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["title"]

    created = MagicMock(id=1, title="New")
    Model.objects.create = AsyncMock(return_value=created)

    ser = PostSerializer.validate({"title": "New"})
    result = await ser.save()
    assert isinstance(result, dict)
    Model.objects.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_serializer_save_updates_when_pk_found_in_db():
    """save() auto-detects update when pk in data resolves to existing record."""
    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "title": _make_field("CharField"),
        }
    )

    class PostSerializer(ModelSerializer):
        id: int | None = None

        class Meta:
            model = Model
            fields = ["title"]

    existing = MagicMock(id=42, title="old")
    existing.save = AsyncMock()
    Model.objects.get = AsyncMock(return_value=existing)

    ser = PostSerializer(id=42, title="Updated")

    with patch.object(
        PostSerializer,
        "update",
        new=AsyncMock(return_value=existing),
    ) as mock_update:
        result = await ser.save()

    mock_update.assert_awaited_once_with(existing)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_model_serializer_save_creates_when_pk_not_found():
    """save() falls through to create() when pk lookup raises DoesNotExist."""
    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "title": _make_field("CharField"),
        }
    )

    class PostSerializer(ModelSerializer):
        id: int | None = None

        class Meta:
            model = Model
            fields = ["title"]

    Model.objects.get = AsyncMock(side_effect=DoesNotExist)
    created = MagicMock(id=99, title="New")
    Model.objects.create = AsyncMock(return_value=created)

    ser = PostSerializer(id=999, title="New")
    result = await ser.save()
    assert isinstance(result, dict)
    Model.objects.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# _validate_file_sizes  (lines 407-418)
# ---------------------------------------------------------------------------


def test_validate_file_sizes_raises_for_invalid_file():
    file_field = _make_field("FileField")
    file_field.validate = MagicMock(side_effect=ValueError("File too large"))

    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "avatar": file_field,
        }
    )

    class AvatarSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["avatar"]

    # Pass a non-string, non-None value to trigger the file validation path
    fake_file = b"fake binary content"
    with pytest.raises(ValidationError) as exc:
        AvatarSerializer._validate_file_sizes({"avatar": fake_file})
    assert any("avatar" in e["field"] for e in exc.value.validation_errors)


def test_validate_file_sizes_skips_string_and_none():
    """String paths and None values are valid (already stored paths)."""
    file_field = _make_field("FileField")
    file_field.validate = MagicMock()

    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "avatar": file_field,
        }
    )

    class AvatarSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["avatar"]

    AvatarSerializer._validate_file_sizes({"avatar": None})
    AvatarSerializer._validate_file_sizes({"avatar": "/media/uploads/photo.jpg"})
    file_field.validate.assert_not_called()


# ---------------------------------------------------------------------------
# PaginatedSerializer  (line 551-558 — ensure instantiation is tested)
# ---------------------------------------------------------------------------


def test_paginated_serializer_basic():
    p = PaginatedSerializer(count=100, results=[{"id": 1}])
    assert p.count == 100
    assert p.next is None
    assert p.previous is None
    assert len(p.results) == 1


def test_paginated_serializer_with_urls():
    p = PaginatedSerializer(
        count=50,
        next="/api/posts/?page=3",
        previous="/api/posts/?page=1",
        results=[],
    )
    assert p.next == "/api/posts/?page=3"
    assert p.previous == "/api/posts/?page=1"


# ---------------------------------------------------------------------------
# _persist_files — bytes / file-like / generic branch  (lines 451-469)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_files_bytes_content():
    file_field = _make_field("FileField")
    file_field.upload_to = "uploads/"

    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "doc": file_field,
        }
    )

    class DocSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["doc"]

    fake_bytes = b"file content"
    with patch(
        "openviper.serializers.base.default_storage.save",
        new=AsyncMock(return_value="uploads/file"),
    ):
        result = await DocSerializer._persist_files({"doc": fake_bytes})
    assert result["doc"] == "uploads/file"


@pytest.mark.asyncio
async def test_persist_files_file_like_object():
    file_field = _make_field("FileField")
    file_field.upload_to = "uploads/"

    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "doc": file_field,
        }
    )

    class DocSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["doc"]

    fake_file = io.BytesIO(b"file bytes")
    fake_file.name = "report.pdf"

    with patch(
        "openviper.serializers.base.default_storage.save",
        new=AsyncMock(return_value="uploads/report.pdf"),
    ):
        result = await DocSerializer._persist_files({"doc": fake_file})
    assert result["doc"] == "uploads/report.pdf"


@pytest.mark.asyncio
async def test_persist_files_deletes_old_file_on_update():
    file_field = _make_field("FileField")
    file_field.upload_to = "media/"

    Model = _make_model_stub(
        fields={
            "id": _make_field("AutoField", primary_key=True),
            "photo": file_field,
        }
    )

    class PhotoSerializer(ModelSerializer):
        class Meta:
            model = Model
            fields = ["photo"]

    old_instance = MagicMock()
    old_instance.photo = "media/old_photo.jpg"

    with (
        patch(
            "openviper.serializers.base.default_storage.save",
            new=AsyncMock(return_value="media/new_photo.jpg"),
        ),
        patch(
            "openviper.serializers.base.default_storage.delete",
            new=AsyncMock(),
        ) as mock_delete,
    ):
        result = await PhotoSerializer._persist_files(
            {"photo": b"newbytes"}, old_instance=old_instance
        )

    mock_delete.assert_awaited_once_with("media/old_photo.jpg")
    assert result["photo"] == "media/new_photo.jpg"
