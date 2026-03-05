import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db import fields
from openviper.db.models import Model
from openviper.exceptions import DoesNotExist, ValidationError
from openviper.serializers import ModelSerializer, PaginatedSerializer, Serializer, field_validator


class SimpleSerializer(Serializer):
    name: str
    age: int = 25
    email: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("Name too short")
        return v.title()


def test_serializer_validation():
    # Success
    data = {"name": "alice", "age": 30}
    ser = SimpleSerializer.validate(data)
    assert ser.name == "Alice"
    assert ser.age == 30
    assert ser.email is None

    # Default value
    ser = SimpleSerializer.validate({"name": "bob"})
    assert ser.age == 25

    # Failure
    with pytest.raises(ValidationError) as exc:
        SimpleSerializer.validate({"name": "a"})
    assert exc.value.validation_errors[0]["field"] == "name"
    assert "Name too short" in exc.value.validation_errors[0]["message"]


def test_serializer_serialize():
    ser = SimpleSerializer(name="Alice", age=30, email="alice@example.com")
    data = ser.serialize()
    assert data == {"name": "Alice", "age": 30, "email": "alice@example.com"}


# ── validate_json_string ──────────────────────────────────────────────────────


def test_validate_json_string_valid():
    json_str = json.dumps({"name": "alice", "age": 30})
    ser = SimpleSerializer.validate_json_string(json_str)
    assert ser.name == "Alice"
    assert ser.age == 30
    assert ser.email is None


def test_validate_json_string_with_optional_field():
    json_str = json.dumps({"name": "bob", "age": 20, "email": "bob@example.com"})
    ser = SimpleSerializer.validate_json_string(json_str)
    assert ser.name == "Bob"
    assert ser.email == "bob@example.com"


def test_validate_json_string_invalid_raises_validation_error():
    # Missing required field 'name'
    json_str = json.dumps({"age": 30})
    with pytest.raises(ValidationError) as exc:
        SimpleSerializer.validate_json_string(json_str)
    assert exc.value.validation_errors[0]["field"] == "name"


def test_validate_json_string_validator_fired():
    # name too short → field validator raises ValueError
    json_str = json.dumps({"name": "x"})
    with pytest.raises(ValidationError) as exc:
        SimpleSerializer.validate_json_string(json_str)
    assert "Name too short" in exc.value.validation_errors[0]["message"]


# ── from_orm_many ─────────────────────────────────────────────────────────────


def test_from_orm_many_empty_list():
    result = SimpleSerializer.from_orm_many([])
    assert result == []


def test_from_orm_many_multiple_objects():
    obj1 = MagicMock()
    obj1.name = "alice"
    obj1.age = 30
    obj1.email = None

    obj2 = MagicMock()
    obj2.name = "bob"
    obj2.age = 25
    obj2.email = "bob@example.com"

    result = SimpleSerializer.from_orm_many([obj1, obj2])
    assert len(result) == 2
    assert result[0].name == "Alice"
    assert result[1].name == "Bob"
    assert result[1].email == "bob@example.com"


# ── serialize() with exclude ──────────────────────────────────────────────────


def test_serialize_with_exclude_parameter():
    ser = SimpleSerializer(name="Alice", age=30, email="alice@example.com")
    data = ser.serialize(exclude={"age"})
    assert "name" in data
    assert "email" in data
    assert "age" not in data


def test_serialize_exclude_multiple_fields():
    ser = SimpleSerializer(name="Alice", age=30, email="alice@example.com")
    data = ser.serialize(exclude={"age", "email"})
    assert "name" in data
    assert "age" not in data
    assert "email" not in data


def test_serialize_exclude_combines_with_write_only():
    class CombinedSerializer(Serializer):
        username: str
        password: str
        secret: str
        write_only_fields = ("password",)

    ser = CombinedSerializer(username="alice", password="secret", secret="hidden")
    data = ser.serialize(exclude={"secret"})
    assert "username" in data
    assert "password" not in data  # excluded by write_only_fields
    assert "secret" not in data  # excluded by the explicit exclude param


# ── serialize_many ────────────────────────────────────────────────────────────


def test_serialize_many_empty_list():
    result = SimpleSerializer.serialize_many([])
    assert result == []


def test_serialize_many_list_of_objects():
    obj1 = MagicMock()
    obj1.name = "alice"
    obj1.age = 30
    obj1.email = None

    obj2 = MagicMock()
    obj2.name = "bob"
    obj2.age = 22
    obj2.email = "bob@example.com"

    result = SimpleSerializer.serialize_many([obj1, obj2])
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["name"] == "Alice"
    assert result[1]["name"] == "Bob"


def test_serialize_many_with_exclude():
    obj = MagicMock()
    obj.name = "alice"
    obj.age = 30
    obj.email = "alice@example.com"

    result = SimpleSerializer.serialize_many([obj], exclude={"age"})
    assert len(result) == 1
    assert "age" not in result[0]
    assert result[0]["name"] == "Alice"


# ── serialize_json ─────────────────────────────────────────────────────────────


def test_serialize_json_returns_bytes():
    ser = SimpleSerializer(name="alice", age=30)
    result = ser.serialize_json()
    assert isinstance(result, bytes)


def test_serialize_json_content_matches_serialize():
    ser = SimpleSerializer(name="alice", age=30, email="alice@example.com")
    as_dict = ser.serialize()
    as_json = ser.serialize_json()
    assert json.loads(as_json) == as_dict


def test_serialize_json_with_exclude():
    ser = SimpleSerializer(name="alice", age=30, email="alice@example.com")
    result = ser.serialize_json(exclude={"age"})
    data = json.loads(result)
    assert "age" not in data
    assert data["name"] == "Alice"


def test_serialize_json_excludes_write_only_fields():
    class SecureSerializer(Serializer):
        username: str
        password: str
        write_only_fields = ("password",)

    ser = SecureSerializer(username="alice", password="secret")
    data = json.loads(ser.serialize_json())
    assert data["username"] == "alice"
    assert "password" not in data


def test_serialize_json_exclude_combines_with_write_only():
    class CombinedSerializer(Serializer):
        username: str
        password: str
        secret: str
        write_only_fields = ("password",)

    ser = CombinedSerializer(username="alice", password="secret", secret="hidden")
    data = json.loads(ser.serialize_json(exclude={"secret"}))
    assert "username" in data
    assert "password" not in data
    assert "secret" not in data


# ── serialize_many_json ────────────────────────────────────────────────────────


def test_serialize_many_json_empty_list():
    result = SimpleSerializer.serialize_many_json([])
    assert result == b"[]"


def test_serialize_many_json_returns_bytes():
    obj = MagicMock()
    obj.name = "alice"
    obj.age = 30
    obj.email = None
    result = SimpleSerializer.serialize_many_json([obj])
    assert isinstance(result, bytes)


def test_serialize_many_json_content_matches_serialize_many():
    obj1 = MagicMock()
    obj1.name = "alice"
    obj1.age = 30
    obj1.email = None

    obj2 = MagicMock()
    obj2.name = "bob"
    obj2.age = 22
    obj2.email = "bob@example.com"

    as_list = SimpleSerializer.serialize_many([obj1, obj2])
    as_json = SimpleSerializer.serialize_many_json([obj1, obj2])
    assert json.loads(as_json) == as_list


def test_serialize_many_json_with_exclude():
    obj = MagicMock()
    obj.name = "alice"
    obj.age = 30
    obj.email = "alice@example.com"

    result = json.loads(SimpleSerializer.serialize_many_json([obj], exclude={"age"}))
    assert len(result) == 1
    assert "age" not in result[0]
    assert result[0]["name"] == "Alice"


# ── ModelSerializer ───────────────────────────────────────────────────────────


class User(Model):
    username = fields.CharField(max_length=50)
    email = fields.CharField(max_length=100, null=True)
    is_active = fields.BooleanField(default=True)


class UserModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"


def test_model_serializer_generation():
    assert "username" in UserModelSerializer.model_fields
    assert "email" in UserModelSerializer.model_fields
    assert "is_active" in UserModelSerializer.model_fields

    # Check types
    assert UserModelSerializer.model_fields["username"].annotation is str
    # email is null=True, so it should be optional
    # Pydantic v2 might show it as str | None
    annotation = UserModelSerializer.model_fields["email"].annotation
    assert str in annotation.__args__
    assert type(None) in annotation.__args__


@pytest.mark.asyncio
async def test_model_serializer_from_orm():
    user = User(username="alice", email="alice@example.com")
    ser = UserModelSerializer.from_orm(user)
    assert ser.username == "alice"
    assert ser.email == "alice@example.com"
    assert ser.is_active is True


class ReadOnlySerializer(UserModelSerializer):
    class Meta:
        model = User
        fields = ["username", "email"]
        read_only_fields = ("email",)


def test_read_only_fields():
    ser = ReadOnlySerializer(username="alice", email="alice@example.com")
    # serialize should still include it
    data = ser.serialize()
    assert data["email"] == "alice@example.com"


class WriteOnlySerializer(Serializer):
    username: str
    password: str

    # OpenViper Serializer has write_only_fields logic
    write_only_fields = ("password",)


def test_write_only_fields():
    ser = WriteOnlySerializer(username="alice", password="secret_password")
    data = ser.serialize()
    assert "username" in data
    assert "password" not in data


# ── _ModelSerializerMeta extra_kwargs ─────────────────────────────────────────


class ArticleModel(Model):
    title = fields.CharField(max_length=200)
    body = fields.TextField()


def test_extra_kwargs_required_false_makes_field_optional():
    """extra_kwargs with required=False should make the field optional (None default)."""

    class ArticleSerializer(ModelSerializer):
        class Meta:
            model = ArticleModel
            fields = ["title", "body"]
            extra_kwargs = {"title": {"required": False}}

    # title should be optional (allows None)
    annotation = ArticleSerializer.model_fields["title"].annotation
    assert type(None) in annotation.__args__
    # We can construct without title
    ser = ArticleSerializer(title=None, body="some body")
    assert ser.title is None


def test_extra_kwargs_not_present_keeps_required():
    """Fields without extra_kwargs overrides keep their original optionality."""

    class StrictSerializer(ModelSerializer):
        class Meta:
            model = ArticleModel
            fields = ["title", "body"]
            extra_kwargs = {}

    # title has no null/auto config so it should be required (str, not str | None)
    annotation = StrictSerializer.model_fields["title"].annotation
    assert annotation is str


# ── _get_file_fields ──────────────────────────────────────────────────────────


class DocumentModel(Model):
    name = fields.CharField(max_length=100)
    attachment = fields.FileField(upload_to="docs/")


class DocumentSerializer(ModelSerializer):
    class Meta:
        model = DocumentModel
        fields = "__all__"


def test_get_file_fields_returns_file_fields():
    file_fields = DocumentSerializer._get_file_fields()
    assert "attachment" in file_fields
    assert "name" not in file_fields


def test_get_file_fields_empty_when_no_file_fields():
    file_fields = UserModelSerializer._get_file_fields()
    assert file_fields == {}


# ── _validate_file_sizes ──────────────────────────────────────────────────────


def test_validate_file_sizes_no_file_value_skips():
    # When attachment is None (not provided), no error should be raised
    data = {"name": "doc", "attachment": None}
    DocumentSerializer._validate_file_sizes(data)  # should not raise


def test_validate_file_sizes_string_value_skips():
    # When attachment is already a string path, skip validation
    data = {"name": "doc", "attachment": "docs/existing.pdf"}
    DocumentSerializer._validate_file_sizes(data)  # should not raise


def test_validate_file_sizes_exceeds_limit_raises():
    # Simulate a file object whose size exceeds the field's limit
    MagicMock()
    # Use bytes so FileField._get_content_size returns a real size
    # Override the max_file_size on the field to a tiny value
    tiny_bytes = b"x" * 10

    class SmallFileModel(Model):
        doc = fields.FileField(upload_to="docs/", max_file_size=5)  # 5-byte limit

    class SmallFileSerializer(ModelSerializer):
        class Meta:
            model = SmallFileModel
            fields = ["doc"]

    with pytest.raises(ValidationError) as exc:
        SmallFileSerializer._validate_file_sizes({"doc": tiny_bytes})
    assert any(e["field"] == "doc" for e in exc.value.validation_errors)


def test_validate_file_sizes_within_limit_ok():
    class SmallFileModel2(Model):
        doc = fields.FileField(upload_to="docs/", max_file_size=100)

    class SmallFileSerializer2(ModelSerializer):
        class Meta:
            model = SmallFileModel2
            fields = ["doc"]

    SmallFileSerializer2._validate_file_sizes({"doc": b"hello"})  # 5 bytes < 100


# ── _persist_files ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_files_no_file_fields_returns_data_unchanged():
    data = {"username": "alice", "email": "a@example.com"}
    result = await UserModelSerializer._persist_files(data)
    assert result == data


@pytest.mark.asyncio
async def test_persist_files_none_value_skips():
    data = {"name": "doc", "attachment": None}
    with patch("openviper.serializers.base.default_storage") as mock_storage:
        result = await DocumentSerializer._persist_files(data)
    mock_storage.save.assert_not_called()
    assert result["attachment"] is None


@pytest.mark.asyncio
async def test_persist_files_string_value_skips():
    data = {"name": "doc", "attachment": "docs/existing.pdf"}
    with patch("openviper.serializers.base.default_storage") as mock_storage:
        result = await DocumentSerializer._persist_files(data)
    mock_storage.save.assert_not_called()
    assert result["attachment"] == "docs/existing.pdf"


@pytest.mark.asyncio
async def test_persist_files_bytes_value_saved():
    content = b"file content"
    data = {"name": "doc", "attachment": content}

    with patch("openviper.serializers.base.default_storage") as mock_storage:
        mock_storage.save = AsyncMock(return_value="docs/file")
        result = await DocumentSerializer._persist_files(data)

    mock_storage.save.assert_called_once()
    assert result["attachment"] == "docs/file"


@pytest.mark.asyncio
async def test_persist_files_deletes_old_file_on_update():
    content = b"new content"
    data = {"name": "doc", "attachment": content}

    old_instance = MagicMock()
    old_instance.attachment = "docs/old_file.pdf"

    with patch("openviper.serializers.base.default_storage") as mock_storage:
        mock_storage.save = AsyncMock(return_value="docs/new_file.pdf")
        mock_storage.delete = AsyncMock()
        result = await DocumentSerializer._persist_files(data, old_instance=old_instance)

    mock_storage.delete.assert_called_once_with("docs/old_file.pdf")
    mock_storage.save.assert_called_once()
    assert result["attachment"] == "docs/new_file.pdf"


@pytest.mark.asyncio
async def test_persist_files_file_like_object_read():
    mock_file = MagicMock()
    mock_file.filename = "report.pdf"
    mock_file.read = MagicMock(return_value=b"pdf bytes")

    data = {"name": "doc", "attachment": mock_file}

    with patch("openviper.serializers.base.default_storage") as mock_storage:
        mock_storage.save = AsyncMock(return_value="docs/report.pdf")
        result = await DocumentSerializer._persist_files(data)

    mock_storage.save.assert_called_once()
    assert result["attachment"] == "docs/report.pdf"


# ── ModelSerializer.create() ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_serializer_create():
    ser = UserModelSerializer(username="newuser", email="new@example.com", is_active=True)

    mock_instance = MagicMock()
    mock_instance.username = "newuser"
    mock_instance.email = "new@example.com"
    mock_instance.is_active = True
    mock_instance.id = 1

    with patch.object(
        User.objects, "create", new=AsyncMock(return_value=mock_instance)
    ) as mock_create:
        result = await ser.create()

    mock_create.assert_called_once()
    assert result is mock_instance


@pytest.mark.asyncio
async def test_model_serializer_create_strips_read_only_fields():
    class ProtectedSerializer(ModelSerializer):
        class Meta:
            model = User
            fields = ["username", "email"]
            read_only_fields = ("email",)

    ser = ProtectedSerializer(username="alice", email="alice@example.com")

    mock_instance = MagicMock()
    mock_instance.username = "alice"
    mock_instance.email = None
    mock_instance.id = 1

    with patch.object(
        User.objects, "create", new=AsyncMock(return_value=mock_instance)
    ) as mock_create:
        await ser.create()

    call_kwargs = mock_create.call_args[1]
    assert "email" not in call_kwargs


# ── ModelSerializer.update() ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_serializer_update():
    ser = UserModelSerializer(username="updated", email="up@example.com", is_active=False)

    mock_instance = MagicMock()
    mock_instance.id = 5
    mock_instance.save = AsyncMock()

    result = await ser.update(mock_instance)

    assert mock_instance.username == "updated"
    assert mock_instance.email == "up@example.com"
    assert mock_instance.is_active is False
    mock_instance.save.assert_called_once()
    assert result is mock_instance


@pytest.mark.asyncio
async def test_model_serializer_update_does_not_change_pk():
    ser = UserModelSerializer(username="updated", email=None, is_active=True)
    ser.model_dump()
    assert True  # id may or may not be present

    mock_instance = MagicMock()
    mock_instance.id = 99
    mock_instance.save = AsyncMock()

    await ser.update(mock_instance)

    # The pk on the instance should NOT be overwritten to None
    assert mock_instance.id == 99


# ── ModelSerializer.save() ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_with_explicit_instance_calls_update():
    ser = UserModelSerializer(username="updated", email=None, is_active=True)

    mock_instance = MagicMock()
    mock_instance.id = 10
    mock_instance.username = "updated"
    mock_instance.email = None
    mock_instance.is_active = True
    mock_instance.save = AsyncMock()

    result = await ser.save(instance=mock_instance)

    mock_instance.save.assert_called_once()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_save_without_pk_calls_create():
    ser = UserModelSerializer(username="newuser", email=None, is_active=True)

    mock_instance = MagicMock()
    mock_instance.username = "newuser"
    mock_instance.email = None
    mock_instance.is_active = True
    mock_instance.id = None

    with patch.object(User.objects, "create", new=AsyncMock(return_value=mock_instance)):
        result = await ser.save()

    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_save_with_pk_existing_record_calls_update():
    """When the serializer holds an id that resolves to an existing DB record, update is called."""

    class UserWithIdSerializer(ModelSerializer):
        class Meta:
            model = User
            fields = "__all__"

    ser = UserWithIdSerializer(username="alice", email=None, is_active=True, id=42)

    mock_existing = MagicMock()
    mock_existing.id = 42
    mock_existing.username = "alice"
    mock_existing.email = None
    mock_existing.is_active = True
    mock_existing.save = AsyncMock()

    with patch.object(User.objects, "get", new=AsyncMock(return_value=mock_existing)):
        result = await ser.save()

    mock_existing.save.assert_called_once()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_save_with_pk_nonexistent_record_calls_create():
    """When the id is present but the record isn't found, create is called."""

    class UserWithIdSerializer2(ModelSerializer):
        class Meta:
            model = User
            fields = "__all__"

    ser = UserWithIdSerializer2(username="ghost", email=None, is_active=True, id=999)

    mock_new = MagicMock()
    mock_new.username = "ghost"
    mock_new.email = None
    mock_new.is_active = True
    mock_new.id = None

    with (
        patch.object(User.objects, "get", new=AsyncMock(side_effect=DoesNotExist)),
        patch.object(User.objects, "create", new=AsyncMock(return_value=mock_new)),
    ):
        result = await ser.save()

    assert isinstance(result, dict)


# ── PaginatedSerializer ───────────────────────────────────────────────────────


def test_paginated_serializer_basic():
    data = PaginatedSerializer(count=3, results=[{"id": 1}, {"id": 2}, {"id": 3}])
    assert data.count == 3
    assert data.next is None
    assert data.previous is None
    assert len(data.results) == 3


def test_paginated_serializer_with_pagination_links():
    data = PaginatedSerializer(
        count=100,
        next="http://api.example.com/items/?page=3",
        previous="http://api.example.com/items/?page=1",
        results=[{"id": i} for i in range(10)],
    )
    assert data.count == 100
    assert "page=3" in data.next
    assert "page=1" in data.previous
    assert len(data.results) == 10


def test_paginated_serializer_empty_results():
    data = PaginatedSerializer(count=0, results=[])
    assert data.count == 0
    assert data.results == []


def test_paginated_serializer_dict_round_trip():
    payload = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [{"name": "a"}, {"name": "b"}],
    }
    ser = PaginatedSerializer.model_validate(payload)
    dumped = ser.model_dump()
    assert dumped["count"] == 2
    assert dumped["results"] == [{"name": "a"}, {"name": "b"}]
