"""Unit tests for openviper/db/fields.py."""

from __future__ import annotations

import datetime
import math
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import openviper.db.fields as fields_mod
from openviper.db.fields import (
    AutoField,
    BinaryField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    EmailField,
    Field,
    FileField,
    FloatField,
    ForeignKey,
    ImageField,
    IntegerField,
    IPAddressField,
    JSONField,
    LazyFK,
    ManyToManyField,
    OneToOneField,
    PositiveIntegerField,
    SlugField,
    TextField,
    TimeField,
    URLField,
    UUIDField,
)
from openviper.db.models import Model, ModelMeta
from openviper.http.request import UploadFile


class DummyModel:
    pass


def dummy_getter():
    return DummyModel


@pytest.fixture(autouse=True)
def reset_registry():
    old_reg = ModelMeta.registry.copy()
    old_index = ModelMeta._name_index.copy()
    ModelMeta.registry.clear()
    ModelMeta._name_index.clear()
    yield
    ModelMeta.registry = old_reg
    ModelMeta._name_index = old_index


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_char(max_length: int = 100, **kwargs) -> CharField:
    return CharField(max_length=max_length, **kwargs)


def make_int(**kwargs) -> IntegerField:
    return IntegerField(**kwargs)


def make_datetime(**kwargs) -> DateTimeField:
    return DateTimeField(**kwargs)


def make_fk(to="OtherModel", **kwargs) -> ForeignKey:
    return ForeignKey(to=to, **kwargs)


# ---------------------------------------------------------------------------
# Field base
# ---------------------------------------------------------------------------


class TestFieldBase:
    @pytest.mark.asyncio
    async def test_pre_save_base(self):
        f = Field()
        await f.pre_save(MagicMock(), 42)

    def test_default_attributes(self):
        f = Field()
        assert f.primary_key is False
        assert f.null is False
        assert f.unique is False
        assert f.db_index is False
        assert f.default is None
        assert f.choices == []
        assert f.help_text == ""

    def test_column_name_defaults_to_name(self):
        f = Field()
        f.name = "title"
        assert f.column_name == "title"

    def test_column_name_overridden_by_db_column(self):
        f = Field(db_column="my_col")
        f.name = "title"
        assert f.column_name == "my_col"

    def test_validate_null_raises(self):
        f = Field(null=False)
        f.name = "x"
        with pytest.raises(ValueError, match="cannot be null"):
            f.validate(None)

    def test_validate_null_allowed(self):
        f = Field(null=True)
        f.name = "x"
        f.validate(None)  # should not raise

    def test_validate_choices_valid(self):
        f = Field(choices=[("a", "A"), ("b", "B")])
        f.name = "c"
        f.validate("a")  # no raise

    def test_validate_choices_invalid(self):
        f = Field(choices=[("a", "A")])
        f.name = "c"
        with pytest.raises(ValueError, match="not in choices"):
            f.validate("z")

    def test_validate_choices_rebuild_set(self):
        f = Field()
        f.name = "test"
        f.choices = [(1, "One")]
        f._choices_set = frozenset()
        f.validate(1)
        assert f._choices_set == frozenset([1])

    def test_repr(self):
        f = Field()
        f.name = "my_field"
        assert "my_field" in repr(f)

    def test_to_python_identity(self):
        f = Field()
        assert f.to_python("x") == "x"

    def test_to_db_identity(self):
        f = Field()
        assert f.to_db(42) == 42


# ---------------------------------------------------------------------------
# AutoField
# ---------------------------------------------------------------------------


class TestAutoField:
    def test_is_primary_key(self):
        f = AutoField()
        assert f.primary_key is True
        assert f.auto_increment is True

    def test_to_python_int(self):
        f = AutoField()
        assert f.to_python("5") == 5

    def test_to_python_none(self):
        f = AutoField()
        assert f.to_python(None) is None


# ---------------------------------------------------------------------------
# IntegerField / BigIntegerField / FloatField
# ---------------------------------------------------------------------------


class TestIntegerField:
    @pytest.mark.parametrize(
        ("val", "expected"),
        [
            ("42", 42),
            (3.9, 3),
            (0, 0),
        ],
    )
    def test_to_python(self, val, expected):
        assert make_int().to_python(val) == expected

    def test_to_python_none(self):
        assert make_int().to_python(None) is None

    def test_to_db(self):
        assert make_int().to_db("7") == 7


class TestFloatField:
    def test_to_python(self):
        f = FloatField()
        assert f.to_python("3.14") == pytest.approx(3.14)

    def test_to_python_none(self):
        assert FloatField().to_python(None) is None


# ---------------------------------------------------------------------------
# DecimalField
# ---------------------------------------------------------------------------


class TestDecimalField:
    def test_to_python_string(self):
        f = DecimalField()
        assert f.to_python("3.14") == Decimal("3.14")

    def test_to_python_none(self):
        assert DecimalField().to_python(None) is None

    def test_stores_precision(self):
        f = DecimalField(max_digits=8, decimal_places=3)
        assert f.max_digits == 8
        assert f.decimal_places == 3


# ---------------------------------------------------------------------------
# CharField
# ---------------------------------------------------------------------------


class TestCharField:
    def test_to_python(self):
        f = make_char()
        assert f.to_python(42) == "42"

    def test_to_python_none(self):
        assert make_char().to_python(None) is None

    def test_validate_max_length_ok(self):
        f = make_char(max_length=5)
        f.name = "x"
        f.validate("abc")  # no raise

    def test_validate_max_length_exceeded(self):
        f = make_char(max_length=3)
        f.name = "x"
        with pytest.raises(ValueError, match="max_length"):
            f.validate("toolong")


# ---------------------------------------------------------------------------
# TextField
# ---------------------------------------------------------------------------


class TestTextField:
    def test_to_python(self):
        assert TextField().to_python(123) == "123"

    def test_to_python_none(self):
        assert TextField().to_python(None) is None


# ---------------------------------------------------------------------------
# PositiveIntegerField
# ---------------------------------------------------------------------------


class TestPositiveIntegerField:
    def test_validate_positive(self):
        f = PositiveIntegerField()
        f.name = "pos"
        f.validate(5)  # ok

    def test_validate_negative_raises(self):
        f = PositiveIntegerField()
        f.name = "pos"
        with pytest.raises(ValueError, match="must be >= 0"):
            f.validate(-1)


# ---------------------------------------------------------------------------
# BooleanField
# ---------------------------------------------------------------------------


class TestBooleanField:
    @pytest.mark.parametrize(
        ("val", "expected"),
        [
            (True, True),
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            (False, False),
            ("false", False),
            ("0", False),
        ],
    )
    def test_to_python(self, val, expected):
        assert BooleanField().to_python(val) == expected

    def test_to_python_none(self):
        assert BooleanField().to_python(None) is None

    def test_to_db_true(self):
        assert BooleanField().to_db(True) == 1

    def test_to_db_false(self):
        assert BooleanField().to_db(False) == 0

    def test_to_db_none(self):
        assert BooleanField().to_db(None) is None


# ---------------------------------------------------------------------------
# DateTimeField
# ---------------------------------------------------------------------------


class TestDateTimeField:
    def test_to_python_none(self):
        assert make_datetime().to_python(None) is None

    def test_to_python_datetime_passthrough(self):
        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        result = make_datetime().to_python(dt)
        assert isinstance(result, datetime.datetime)

    def test_to_python_string(self):
        result = make_datetime().to_python("2024-01-01T12:00:00+00:00")
        assert isinstance(result, datetime.datetime)

    def test_auto_now_stored(self):
        f = DateTimeField(auto_now=True)
        assert f.auto_now is True

    def test_auto_now_add_stored(self):
        f = DateTimeField(auto_now_add=True)
        assert f.auto_now_add is True

    def test_to_db_none(self):
        assert make_datetime().to_db(None) is None

    async def test_to_python_naive_aware(self):
        f = make_datetime()
        dt_naive = datetime.datetime(2023, 1, 1, 12, 0)
        dt_aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.UTC)

        with patch("openviper.db.fields.settings") as mock_settings:
            mock_settings.USE_TZ = True
            # naive -> aware
            aware = f.to_python(dt_naive)
            assert aware.tzinfo is not None
            # aware -> aware (different tz astimezone)
            aware2 = f.to_python(dt_aware)
            assert aware2.tzinfo is not None

            mock_settings.USE_TZ = False
            # aware -> naive
            naive = f.to_python(aware)
            assert naive.tzinfo is None
            # naive -> naive
            naive2 = f.to_python(dt_naive)
            assert naive2.tzinfo is None

    async def test_to_db_naive_aware(self):
        f = make_datetime()
        dt_naive = datetime.datetime(2023, 1, 1, 12, 0)
        dt_aware = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.UTC)

        with patch("openviper.db.fields.settings") as mock_settings:
            mock_settings.USE_TZ = True
            # naive -> aware_db
            aware_db = f.to_db(dt_naive)
            assert aware_db.tzinfo is not None
            # aware -> aware_db
            aware_db2 = f.to_db(dt_aware)
            assert aware_db2.tzinfo is not None

            mock_settings.USE_TZ = False
            # aware -> naive_db
            naive_db = f.to_db(aware_db)
            assert naive_db.tzinfo is None
            # naive -> naive_db
            naive_db2 = f.to_db(dt_naive)
            assert naive_db2.tzinfo is None

    def test_to_python_string_iso(self):
        f = make_datetime()
        dt = f.to_python("2023-01-01T12:00:00")
        assert isinstance(dt, datetime.datetime)
        assert dt.year == 2023

    def test_to_db_string_iso(self):
        f = make_datetime()
        dt = f.to_db("2023-01-01T12:00:00")
        assert isinstance(dt, datetime.datetime)
        assert dt.year == 2023


# ---------------------------------------------------------------------------
# DateField
# ---------------------------------------------------------------------------


class TestDateField:
    def test_to_python_none(self):
        assert DateField().to_python(None) is None

    def test_to_python_date_passthrough(self):
        d = datetime.date(2024, 1, 1)
        assert DateField().to_python(d) == d

    def test_to_python_string(self):
        assert DateField().to_python("2024-01-01") == datetime.date(2024, 1, 1)


# ---------------------------------------------------------------------------
# TimeField
# ---------------------------------------------------------------------------


class TestTimeField:
    def test_to_python_none(self):
        assert TimeField().to_python(None) is None

    def test_to_python_time_passthrough(self):
        t = datetime.time(12, 30)
        assert TimeField().to_python(t) == t

    def test_to_python_string(self):
        assert TimeField().to_python("12:30:00") == datetime.time(12, 30, 0)


# ---------------------------------------------------------------------------
# BinaryField
# ---------------------------------------------------------------------------


class TestBinaryField:
    def test_to_python_bytes(self):
        assert BinaryField().to_python(b"hello") == b"hello"

    def test_to_python_string(self):
        assert BinaryField().to_python("hello") == b"hello"

    def test_to_python_none(self):
        f = BinaryField()
        assert f.to_python(None) is None
        assert f.to_python("hello") == b"hello"
        assert f.to_python([1, 2]) == b"\x01\x02"

    def test_to_db(self):
        assert BinaryField().to_db(b"x") == b"x"


# ---------------------------------------------------------------------------
# UUIDField
# ---------------------------------------------------------------------------


class TestUUIDField:
    def test_to_python_uuid(self):
        u = uuid.uuid4()
        assert UUIDField().to_python(str(u)) == u

    def test_to_python_none(self):
        assert UUIDField().to_python(None) is None

    def test_to_python_uuid_passthrough(self):
        u = uuid.uuid4()
        assert UUIDField().to_python(u) == u

    def test_to_db(self):
        u = uuid.uuid4()
        assert UUIDField().to_db(u) == u

    def test_to_db_from_string(self):
        u = uuid.uuid4()
        assert UUIDField().to_db(str(u)) == u

    def test_to_db_none(self):
        assert UUIDField().to_db(None) is None

    def test_auto_generates_uuid(self):
        f = UUIDField(auto=True)
        assert callable(f.default)


# ---------------------------------------------------------------------------
# JSONField
# ---------------------------------------------------------------------------


class TestJSONField:
    def test_to_python_string(self):
        assert JSONField().to_python('{"a": 1}') == {"a": 1}

    def test_to_python_none(self):
        assert JSONField().to_python(None) is None

    def test_to_python_dict_passthrough(self):
        d = {"x": 1}
        assert JSONField().to_python(d) == d

    def test_to_db_dict(self):
        result = JSONField().to_db({"a": 1})
        # to_db returns the Python object unchanged; SQLAlchemy's JSON type
        # handles serialization natively (returning a string here would cause
        # double-encoding).
        assert result == {"a": 1}

    def test_to_db_none(self):
        assert JSONField().to_db(None) is None


# ---------------------------------------------------------------------------
# ForeignKey
# ---------------------------------------------------------------------------


class TestForeignKey:
    def test_stores_to(self):
        f = make_fk("User")
        assert f.to == "User"

    def test_default_on_delete(self):
        assert make_fk().on_delete == "CASCADE"

    def test_custom_on_delete(self):
        f = ForeignKey(to="X", on_delete="SET_NULL")
        assert f.on_delete == "SET_NULL"

    def test_related_name(self):
        f = ForeignKey(to="X", related_name="posts")
        assert f.related_name == "posts"

    def test_resolve_target_with_class(self):
        class Dummy:
            pass

        f = ForeignKey(to=Dummy)
        assert f.resolve_target() is Dummy

    def test_resolve_target_with_callable(self):
        class Dummy:
            pass

        f = ForeignKey(to=lambda: Dummy)
        result = f.resolve_target()
        assert result is Dummy

    def test_resolve_target_with_string_not_found(self):
        f = ForeignKey(to="nonexistent.Model")
        # Should not raise, returns None or resolves
        result = f.resolve_target()
        assert result is None

    def test_resolve_target_registry_key(self):
        class MyModel:
            pass

        ModelMeta.registry["myapp.MyModel"] = MyModel
        f = ForeignKey(to="myapp.MyModel")
        assert f.resolve_target() is MyModel

    @pytest.mark.asyncio
    async def test_resolve_target_dotted_path(self):
        # resolve via import_string
        f = ForeignKey(to="datetime.datetime")
        assert f.resolve_target() is datetime.datetime

    def test_resolve_target_getter_path(self):
        f = ForeignKey(to="tests.unit.db.test_fields.dummy_getter")
        assert f.resolve_target() is DummyModel

    def test_resolve_target_name_index_conflict(self):

        class MockCandidate1:
            _app_name = "app1"

        class MockCandidate2:
            _app_name = "app2"

        # Manually populate index with a UNIQUE name for this test
        ModelMeta._name_index["ConflictName"] = [MockCandidate1, MockCandidate2]

        f = ForeignKey(to="ConflictName")
        # Should pick first one if no model_class
        assert f.resolve_target() is MockCandidate1

        # Should pick same app if model_class provided
        class MySource(Model):
            class Meta:
                abstract = True

        MySource._app_name = "app2"
        f.model_class = MySource

        result = f.resolve_target()
        assert result is MockCandidate2

    def test_resolve_target_call_exception(self):
        def failing_getter():
            raise Exception("fail")

        f = ForeignKey(to=failing_getter)
        assert f.resolve_target() is None


# ---------------------------------------------------------------------------
# EmailField / SlugField / ManyToManyField
# ---------------------------------------------------------------------------


class TestEmailField:
    def test_is_char_field(self):
        assert issubclass(EmailField, CharField)

    def test_to_python(self):
        assert EmailField().to_python("TEST@EXAMPLE.COM") == "TEST@EXAMPLE.COM"

    def test_validate_invalid_email(self):
        f = EmailField()
        f.name = "email"
        with pytest.raises(ValueError, match="invalid email"):
            f.validate("not-an-email")


class TestIPAddressField:
    def test_max_length(self):
        f = IPAddressField()
        assert f.max_length == 45


class TestURLField:
    def test_max_length(self):
        f = URLField()
        assert f.max_length == 2048


class TestSlugField:
    def test_is_char_field(self):
        assert issubclass(SlugField, CharField)


class TestManyToManyField:
    def test_stores_to(self):
        f = ManyToManyField(to="Tag")
        assert f.to == "Tag"

    def test_through_param(self):
        f = ManyToManyField(to="Tag", through="TagThrough")
        assert f.through == "TagThrough"

    def test_related_name(self):
        f = ManyToManyField(to="Tag", related_name="tagged_items")
        assert f.related_name == "tagged_items"


# ---------------------------------------------------------------------------
# FileField
# ---------------------------------------------------------------------------


class TestFileField:
    def test_max_file_size_from_settings(self):
        with patch("openviper.db.fields.settings") as mock_settings:
            mock_settings.MAX_FILE_SIZE = 500
            f = FileField()
            assert f.max_file_size == 500

    def test_max_file_size_default(self):
        with patch("openviper.db.fields.settings", spec=[]):
            # mock_settings has no MAX_FILE_SIZE
            f = FileField()
            assert f.max_file_size == 10 * 1024 * 1024

    def test_validate_none_null_raises(self):
        f = FileField(null=False)
        f.name = "file"
        with pytest.raises(ValueError, match="cannot be null"):
            f.validate(None)

    def test_validate_string_path(self):
        f = FileField()
        f.name = "file"
        f.validate("uploads/test.txt")  # ok

    def test_validate_size_exceeded(self):
        f = FileField(max_file_size=10)
        f.name = "file"
        with pytest.raises(ValueError, match="exceeds maximum allowed size"):
            f.validate(b"this is too long for 10 bytes")

    @pytest.mark.asyncio
    async def test_pre_save_bytes(self):
        f = FileField(upload_to="test_uploads")
        f.name = "my_file"
        instance = MagicMock()

        content = b"hello world"
        # Mock Path and aiofiles
        with patch("openviper.db.fields.Path"):
            with patch("openviper.db.fields.aiofiles.open") as mock_open:
                mock_f = AsyncMock()
                mock_open.return_value.__aenter__.return_value = mock_f

                await f.pre_save(instance, content)

                assert mock_open.called
                assert mock_f.write.called
                assert mock_f.write.call_args[0][0] == content
                # Path(upload_path / dest_filename)
                assert isinstance(instance.my_file, str)

    @pytest.mark.asyncio
    async def test_pre_save_file_like(self):
        f = FileField()
        f.name = "file"
        instance = MagicMock()

        # Test duck-typed file-like object
        class FakeFile:
            def read(self):
                return b"data"

            name = "test.txt"

        with patch("openviper.db.fields.aiofiles.open") as mock_open:
            mock_f = AsyncMock()
            mock_open.return_value.__aenter__.return_value = mock_f
            await f.pre_save(instance, FakeFile())
            assert mock_f.write.called

    def test_get_content_size_file_like(self):
        f = FileField()

        class SizeyFile:
            size = 100

        assert f._get_content_size(SizeyFile()) == 100

        class SeekyFile:
            def seek(self, *a):
                pass

            def tell(self):
                return 50

            def read(self):
                pass

        assert f._get_content_size(SeekyFile()) == 50

    def test_validate_saved_path(self):
        f = FileField(max_length=5)
        f.name = "f"
        f.validate("abc")  # ok
        with pytest.raises(ValueError, match="max_length"):
            f.validate("too-long")


# ---------------------------------------------------------------------------
# LazyFK
# ---------------------------------------------------------------------------


class TestLazyFK:
    async def test_lazy_fk_basics(self):
        field = MagicMock()
        field.name = "owner"
        # Correct order: fk_field, instance, fk_id
        obj = LazyFK(field, MagicMock(), 1)
        assert obj.fk_id == 1
        assert bool(obj) is True
        assert int(obj) == 1
        assert str(obj) == "1"
        assert hash(obj) == hash(1)
        assert obj == 1
        assert obj == LazyFK(field, MagicMock(), 1)

    @pytest.mark.asyncio
    async def test_lazy_fk_load_db(self):
        field = MagicMock()
        field.resolve_target.return_value = MagicMock()
        instance = MagicMock()
        obj = LazyFK(field, instance, 1)

        # Mock execute_select and _from_row
        mock_model = field.resolve_target.return_value
        mock_model._from_row.return_value = "LOADED_OBJ"

        with patch("openviper.db.executor.execute_select", new_callable=AsyncMock) as mock_select:
            mock_select.return_value = ["row"]
            result = await obj._load()
            assert result == "LOADED_OBJ"
            assert obj._loaded_obj == "LOADED_OBJ"

    def test_lazy_fk_hash_and_bool_none(self):
        obj = LazyFK(MagicMock(), MagicMock(), None)
        assert bool(obj) is False
        assert int(obj) == 0
        assert str(obj) == ""


class TestOneToOneField:
    def test_unique_constraint(self):
        f = OneToOneField(to="Other")
        # Should set unique=True and db_index=False
        assert f.unique is True
        assert f.db_index is False


# ---------------------------------------------------------------------------
# Field.validate — DEBUG=False branches
# ---------------------------------------------------------------------------


class TestFieldValidateDebugFalse:
    def test_null_not_allowed_debug_false(self):
        f = Field(null=False)
        f.name = "x"
        with patch("openviper.db.fields.settings") as m:
            m.DEBUG = False
            with pytest.raises(ValueError, match="Required field cannot be empty"):
                f.validate(None)

    def test_choices_invalid_debug_false(self):
        f = Field(choices=[("a", "A")])
        f.name = "c"
        with patch("openviper.db.fields.settings") as m:
            m.DEBUG = False
            with pytest.raises(ValueError, match="Invalid value: not one of the allowed choices"):
                f.validate("z")


# ---------------------------------------------------------------------------
# AutoField overflow
# ---------------------------------------------------------------------------


class TestAutoFieldOverflow:
    def test_to_python_overflow(self):
        f = AutoField()
        f.name = "id"
        with pytest.raises(ValueError, match="exceeds"):
            f.to_python(2**31)


# ---------------------------------------------------------------------------
# IntegerField overflow / to_db
# ---------------------------------------------------------------------------


class TestIntegerFieldOverflow:
    def test_to_python_overflow(self):
        f = make_int()
        f.name = "num"
        with pytest.raises(ValueError, match="exceeds"):
            f.to_python(2**31)

    def test_to_db_none(self):
        assert make_int().to_db(None) is None

    def test_to_db_overflow(self):
        f = make_int()
        f.name = "num"
        with pytest.raises(ValueError, match="exceeds"):
            f.to_db(2**31)


# ---------------------------------------------------------------------------
# FloatField inf / NaN
# ---------------------------------------------------------------------------


class TestFloatFieldValidation:
    def test_inf_not_allowed(self):
        f = FloatField()
        f.name = "val"
        with pytest.raises(ValueError, match="infinite"):
            f.to_python(float("inf"))

    def test_nan_not_allowed(self):
        f = FloatField()
        f.name = "val"
        with pytest.raises(ValueError, match="NaN"):
            f.to_python(float("nan"))

    def test_inf_allowed(self):
        f = FloatField(allow_inf=True)
        assert math.isinf(f.to_python(float("inf")))

    def test_nan_allowed(self):
        f = FloatField(allow_nan=True)
        assert math.isnan(f.to_python(float("nan")))


# ---------------------------------------------------------------------------
# DecimalField precision
# ---------------------------------------------------------------------------


class TestDecimalFieldPrecision:
    def test_too_many_digits(self):
        f = DecimalField(max_digits=3, decimal_places=2)
        f.name = "price"
        with pytest.raises(ValueError, match="digits"):
            f.to_python("12345")

    def test_too_many_decimal_places(self):
        f = DecimalField(max_digits=10, decimal_places=2)
        f.name = "price"
        with pytest.raises(ValueError, match="decimal places"):
            f.to_python("1.12345")


# ---------------------------------------------------------------------------
# CharField.validate — DEBUG=False
# ---------------------------------------------------------------------------


class TestCharFieldValidateDebugFalse:
    def test_max_length_exceeded_debug_false(self):
        f = CharField(max_length=3)
        f.name = "x"
        with patch("openviper.db.fields.settings") as m:
            m.DEBUG = False
            with pytest.raises(ValueError, match="exceeds maximum length"):
                f.validate("toolong")


# ---------------------------------------------------------------------------
# JSONField max_size
# ---------------------------------------------------------------------------


class TestJSONFieldMaxSize:
    def test_max_size_from_field(self):
        f = JSONField(max_size=10)
        f.name = "data"
        assert f.max_size == 10

    def test_to_python_size_exceeded(self):
        f = JSONField(max_size=5)
        f.name = "data"
        with pytest.raises(ValueError, match="exceeds maximum"):
            f.to_python('{"key": "a very long value that is big"}')

    def test_to_db_size_exceeded(self):
        f = JSONField(max_size=5)
        f.name = "data"
        with pytest.raises(ValueError, match="exceeds maximum"):
            f.to_db({"key": "a very long value that is big"})


# ---------------------------------------------------------------------------
# ForeignKey descriptor (__get__, __set__, to_db)
# ---------------------------------------------------------------------------


class TestForeignKeyDescriptor:
    def test_get_on_class_returns_self(self):
        f = make_fk("User")
        f.name = "author"
        result = f.__get__(None, type(None))
        assert result is f

    def test_get_cached_relation(self):
        f = make_fk("User")
        f.name = "author"
        obj = MagicMock()
        obj._relation_cache = {"author": "cached_user"}
        result = f.__get__(obj, type(obj))
        assert result == "cached_user"

    def test_get_returns_lazy_fk(self):
        f = make_fk("User")
        f.name = "author"
        obj = type("Obj", (), {"__dict__": {"author_id": 42}, "_relation_cache": None})()
        obj.__dict__["author_id"] = 42
        obj._relation_cache = None
        result = f.__get__(obj, type(obj))
        assert isinstance(result, LazyFK)
        assert result.fk_id == 42

    def test_set_model_instance(self):
        f = make_fk("User")
        f.name = "author"

        class FakeModel(Model):
            class Meta:
                abstract = True

        fake = FakeModel.__new__(FakeModel)
        fake.id = 99

        obj = type("Obj", (), {"_relation_cache": {}})()
        obj._set_related = lambda name, val: obj._relation_cache.__setitem__(name, val)
        f.__set__(obj, fake)
        assert obj.__dict__["author_id"] == 99
        assert obj._relation_cache["author"] is fake

    def test_set_raw_value_clears_cache(self):
        f = make_fk("User")
        f.name = "author"
        obj = type("Obj", (), {"_relation_cache": {"author": "old_cached"}})()
        f.__set__(obj, 55)
        assert obj.__dict__["author_id"] == 55
        assert "author" not in obj._relation_cache

    def test_to_db_none(self):
        f = make_fk("User")
        assert f.to_db(None) is None

    def test_to_db_lazy_fk(self):
        f = make_fk("User")
        lazy = LazyFK(f, MagicMock(), 7)
        assert f.to_db(lazy) == 7

    def test_to_db_model_instance(self):
        f = make_fk("User")

        class FakeModel(Model):
            class Meta:
                abstract = True

        fake = FakeModel.__new__(FakeModel)
        fake.id = 42
        assert f.to_db(fake) == 42


# ---------------------------------------------------------------------------
# LazyFK extra methods
# ---------------------------------------------------------------------------


class TestLazyFKExtra:
    def test_await(self):
        field = MagicMock()
        field.name = "owner"
        obj = LazyFK(field, MagicMock(), 5)
        gen = obj.__await__()
        assert hasattr(gen, "__next__")

    def test_index(self):
        obj = LazyFK(MagicMock(), MagicMock(), 3)
        assert obj.__index__() == 3

    def test_get_pydantic_core_schema(self):
        schema = LazyFK.__get_pydantic_core_schema__(LazyFK, lambda x: x)
        assert schema is not None

    def test_validate_with_lazy_fk(self):
        obj = LazyFK(MagicMock(), MagicMock(), 10)
        assert LazyFK._validate(obj) == 10

    def test_validate_with_plain_value(self):
        assert LazyFK._validate(42) == 42

    def test_str_with_loaded_obj(self):
        obj = LazyFK(MagicMock(), MagicMock(), 1)
        obj._loaded_obj = "LoadedUser"
        assert str(obj) == "LoadedUser"

    def test_repr_with_loaded_obj(self):
        obj = LazyFK(MagicMock(), MagicMock(), 1)
        obj._loaded_obj = "LoadedUser"
        assert repr(obj) == "'LoadedUser'"


# ---------------------------------------------------------------------------
# EmailField control characters
# ---------------------------------------------------------------------------


class TestEmailFieldControlChars:
    @pytest.mark.parametrize("bad_char", ["\n", "\r", "\0"])
    def test_control_characters_rejected(self, bad_char):
        f = EmailField()
        f.name = "email"
        with pytest.raises(ValueError, match="forbidden control characters"):
            f.validate(f"user{bad_char}@example.com")


# ---------------------------------------------------------------------------
# FileField additional coverage
# ---------------------------------------------------------------------------


class TestFileFieldExtra:
    def test_max_file_size_exception_path(self):
        with patch("openviper.db.fields.settings") as m:
            type(m).MAX_FILE_SIZE = property(lambda self: (_ for _ in ()).throw(Exception("boom")))
            f = FileField()
            assert f.max_file_size == 10 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_pre_save_path_traversal(self):
        f = FileField(upload_to="uploads")
        f.name = "file"
        instance = MagicMock()
        content = b"data"

        with patch("openviper.db.fields.Path") as mock_path_cls:
            mock_media = MagicMock()
            mock_path_cls.return_value.absolute.return_value.resolve.return_value = mock_media
            mock_dir = MagicMock()
            mock_media.__truediv__ = MagicMock(return_value=mock_dir)
            mock_dir.mkdir = MagicMock()

            mock_full_path = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=MagicMock())
            mock_dir.__truediv__.return_value.resolve.return_value = mock_full_path
            mock_full_path.relative_to = MagicMock(side_effect=ValueError("escape"))

            with patch("openviper.db.fields.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = None
                with pytest.raises(ValueError, match="Path traversal"):
                    await f.pre_save(instance, content)

    def test_sanitize_filename_empty_after_strip(self):
        result = FileField._sanitize_filename("...")
        assert result.startswith("upload_")

    def test_sanitize_filename_too_long(self):
        long_name = "a" * 300 + ".txt"
        result = FileField._sanitize_filename(long_name)
        assert len(result) <= 255

    def test_validate_none_null_true(self):
        f = FileField(null=True)
        f.name = "file"
        f.validate(None)

    def test_get_content_size_unknown_type(self):
        f = FileField()
        assert f._get_content_size(12345) is None

    @pytest.mark.asyncio
    async def test_pre_save_async_file_like(self):
        f = FileField()
        f.name = "file"
        instance = MagicMock()

        class AsyncFile:
            name = "async_test.txt"

            async def read(self):
                return b"async data"

        with patch("openviper.db.fields.Path") as mock_path_cls:
            mock_media = MagicMock()
            mock_path_cls.return_value.absolute.return_value.resolve.return_value = mock_media
            mock_dir = MagicMock()
            mock_media.__truediv__ = MagicMock(return_value=mock_dir)

            mock_full = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=MagicMock())
            mock_dir.__truediv__.return_value.resolve.return_value = mock_full
            mock_full.relative_to = MagicMock(return_value=None)

            with patch("openviper.db.fields.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = None
                with patch("openviper.db.fields.aiofiles.open") as mock_open:
                    mock_f = AsyncMock()
                    mock_open.return_value.__aenter__.return_value = mock_f
                    await f.pre_save(instance, AsyncFile())
                    mock_f.write.assert_called_once_with(b"async data")

    @pytest.mark.asyncio
    async def test_pre_save_upload_file(self):
        f = FileField()
        f.name = "file"
        instance = MagicMock()

        upload = MagicMock(spec=UploadFile)
        upload.filename = "uploaded.txt"
        upload.read = AsyncMock(return_value=b"upload data")

        with patch("openviper.db.fields.Path") as mock_path_cls:
            mock_media = MagicMock()
            mock_path_cls.return_value.absolute.return_value.resolve.return_value = mock_media
            mock_dir = MagicMock()
            mock_media.__truediv__ = MagicMock(return_value=mock_dir)

            mock_full = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=MagicMock())
            mock_dir.__truediv__.return_value.resolve.return_value = mock_full
            mock_full.relative_to = MagicMock(return_value=None)

            with patch("openviper.db.fields.asyncio.to_thread") as mock_thread:
                mock_thread.return_value = None
                with patch("openviper.db.fields.aiofiles.open") as mock_open:
                    mock_f = AsyncMock()
                    mock_open.return_value.__aenter__.return_value = mock_f
                    await f.pre_save(instance, upload)
                    mock_f.write.assert_called_once_with(b"upload data")


# ---------------------------------------------------------------------------
# ImageField
# ---------------------------------------------------------------------------


class TestImageField:
    def test_init_defaults(self):
        f = ImageField()
        assert f.upload_to == "images/"
        assert f.allowed_extensions == ImageField.DEFAULT_ALLOWED_EXTENSIONS

    def test_init_custom_extensions(self):
        f = ImageField(allowed_extensions={"PNG", "JPG"})
        assert f.allowed_extensions == frozenset({"png", "jpg"})

    def test_validate_string_path_good(self):
        f = ImageField()
        f.name = "img"
        f.validate("uploads/photo.jpg")

    def test_validate_string_path_bad_extension(self):
        f = ImageField()
        f.name = "img"
        with pytest.raises(ValueError, match="not allowed"):
            f.validate("uploads/file.exe")

    def test_validate_upload_obj_with_filename(self):
        f = ImageField()
        f.name = "img"

        class FakeUpload:
            filename = "photo.png"
            size = 100

        f.validate(FakeUpload())

    def test_validate_upload_obj_bad_extension(self):
        f = ImageField()
        f.name = "img"

        class FakeUpload:
            filename = "malware.exe"
            size = 100

        with pytest.raises(ValueError, match="not allowed"):
            f.validate(FakeUpload())

    def test_validate_upload_obj_with_name_attr(self):
        f = ImageField()
        f.name = "img"

        class FakeUpload:
            filename = None
            name = "photo.jpeg"
            size = 100

        f.validate(FakeUpload())

    def test_validate_none_returns_early(self):
        f = ImageField(null=True)
        f.name = "img"
        f.validate(None)

    def test_validate_extension_no_ext(self):
        f = ImageField()
        f.name = "img"
        f._validate_extension("noextension")


class TestForeignKeyResolveTargetAppLabel:
    """(ForeignKey.to_db return value fallthrough)."""

    def test_resolve_via_app_label_prepend(self):
        """When FK target is a simple name and app_label prepend finds it."""

        class _AppAuthor(Model):
            name = CharField()

            class Meta:
                table_name = "apptest_authors"

        _AppAuthor._app_name = "apptest"
        full_key = "apptest._AppAuthor"
        ModelMeta.registry[full_key] = _AppAuthor

        fk = ForeignKey("_AppAuthor", on_delete="CASCADE")
        fk.model_class = _AppAuthor  # same app
        result = fk.resolve_target()
        assert result is _AppAuthor
        # Cleanup
        ModelMeta.registry.pop(full_key, None)

    def test_to_db_returns_raw_value(self):
        """to_db returns value unchanged when not None/LazyFK/Model."""
        fk = ForeignKey("SomeTarget", on_delete="CASCADE")
        assert fk.to_db(42) == 42
        assert fk.to_db("string_id") == "string_id"

    def test_to_db_returns_none(self):
        fk = ForeignKey("SomeTarget", on_delete="CASCADE")
        assert fk.to_db(None) is None


class TestLazyFKLoadBranches:
    """Cover LazyFK._load: fk_id=None, resolve_target=None, not results, hydrate."""

    @pytest.mark.asyncio
    async def test_load_returns_none_when_fk_id_none(self):
        fk = ForeignKey("Target", on_delete="CASCADE")
        fk.name = "author"
        inst = MagicMock()
        lazy = LazyFK(fk, inst, fk_id=None)
        result = await lazy._load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_returns_none_when_target_unresolvable(self):
        fk = ForeignKey("NonExistent", on_delete="CASCADE")
        fk.name = "author"
        fk.resolve_target = MagicMock(return_value=None)
        inst = MagicMock()
        lazy = LazyFK(fk, inst, fk_id=1)
        result = await lazy._load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_returns_none_when_no_results(self):
        mock_model = MagicMock()
        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs
        fk = ForeignKey("Target", on_delete="CASCADE")
        fk.name = "author"
        fk.resolve_target = MagicMock(return_value=mock_model)
        inst = MagicMock()
        inst._relation_cache = {}
        lazy = LazyFK(fk, inst, fk_id=99)
        with patch("openviper.db.executor.execute_select", new_callable=AsyncMock, return_value=[]):
            result = await lazy._load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_hydrates_and_caches(self):
        mock_model = MagicMock()
        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs
        mock_row = {"id": 1, "name": "Alice"}
        hydrated = MagicMock()
        mock_model._from_row.return_value = hydrated
        fk = ForeignKey("Target", on_delete="CASCADE")
        fk.name = "author"
        fk.resolve_target = MagicMock(return_value=mock_model)
        inst = MagicMock()
        inst._relation_cache = {}
        inst._set_related = lambda name, val: inst._relation_cache.__setitem__(name, val)
        lazy = LazyFK(fk, inst, fk_id=1)
        with patch(
            "openviper.db.executor.execute_select", new_callable=AsyncMock, return_value=[mock_row]
        ):
            result = await lazy._load()
        assert result is hydrated
        assert inst._relation_cache["author"] is hydrated


class TestLazyFKIndexAndPydantic:
    def test_index_returns_int(self):
        fk = ForeignKey("T", on_delete="CASCADE")
        fk.name = "x"
        lazy = LazyFK(fk, MagicMock(), fk_id=7)
        assert lazy.__index__() == 7

    def test_index_returns_zero_when_none(self):
        fk = ForeignKey("T", on_delete="CASCADE")
        fk.name = "x"
        lazy = LazyFK(fk, MagicMock(), fk_id=None)
        assert lazy.__index__() == 0

    def test_pydantic_core_schema_fallback(self):
        original = fields_mod.core_schema
        try:
            fields_mod.core_schema = None
            schema = LazyFK.__get_pydantic_core_schema__(None, None)
            assert schema == {"type": "any"}
        finally:
            fields_mod.core_schema = original


class TestSlugFieldDefaults:
    def test_slugfield_default_max_length(self):
        f = SlugField()
        assert f.max_length == 50

    def test_slugfield_custom_max_length(self):
        f = SlugField(max_length=100)
        assert f.max_length == 100


class TestIPAddressFieldDefaults:
    def test_ip_default_max_length(self):
        f = IPAddressField()
        assert f.max_length == 45


class TestFileFieldMaxSizeFallback:
    def test_max_file_size_exception_returns_default(self):
        f = FileField()
        f.name = "doc"
        # Mock settings so MAX_FILE_SIZE raises
        with patch("openviper.db.fields.settings") as mock_settings:
            type(mock_settings).MAX_FILE_SIZE = property(
                lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
            )
            result = f.max_file_size
            assert result == 10 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_pre_save_string_value_returns_early(self):
        f = FileField()
        f.name = "doc"
        inst = MagicMock()
        await f.pre_save(inst, "already_saved.txt")
        # No exception means it returned early

    @pytest.mark.asyncio
    async def test_pre_save_none_returns_early(self):
        f = FileField()
        f.name = "doc"
        inst = MagicMock()
        await f.pre_save(inst, None)

    @pytest.mark.asyncio
    async def test_pre_save_unknown_type_returns_early(self):
        f = FileField()
        f.name = "doc"
        inst = MagicMock()
        await f.pre_save(inst, 12345)  # int, not file-like
