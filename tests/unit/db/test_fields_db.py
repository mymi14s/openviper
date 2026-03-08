import datetime
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from openviper.db import fields


def test_base_field():
    f = fields.Field(primary_key=True, default="xyz", db_column="my_col")
    f.name = "test_f"

    assert f.column_name == "my_col"
    assert f.to_python(123) == 123
    assert f.to_db(123) == 123

    # Validation
    f.null = False
    with pytest.raises(ValueError, match="cannot be null"):
        f.validate(None)

    f.choices = [("A", "Alpha"), ("B", "Beta")]
    f.validate("A")
    with pytest.raises(ValueError, match="not in choices"):
        f.validate("C")


def test_numeric_fields():
    # Integer
    i = fields.IntegerField()
    assert i.to_python("10") == 10
    assert i.to_db("10") == 10
    assert i.to_python(None) is None

    # BigInteger
    bi = fields.BigIntegerField()
    assert bi.to_python("100") == 100

    # Float
    fl = fields.FloatField()
    assert fl.to_python("10.5") == 10.5

    # Decimal
    df = fields.DecimalField(max_digits=5, decimal_places=2)
    assert df.to_python(10.5) == Decimal("10.5")

    # Positive Integer
    pi = fields.PositiveIntegerField()
    pi.name = "age"
    pi.validate(10)
    with pytest.raises(ValueError, match="must be >= 0"):
        pi.validate(-5)


def test_char_text_fields():
    c = fields.CharField(max_length=5)
    c.name = "short"
    assert c.to_python(123) == "123"

    c.validate("12345")
    with pytest.raises(ValueError, match="exceeds max_length"):
        c.validate("123456")

    t = fields.TextField()
    assert t.to_python(123) == "123"


def test_boolean_field():
    b = fields.BooleanField()
    assert b.to_python("true") is True
    assert b.to_python(0) is False
    assert b.to_python(None) is None

    assert b.to_db(True) == 1
    assert b.to_db(False) == 0


def test_datetime_fields():
    dt = fields.DateTimeField()
    now = datetime.datetime.now(datetime.UTC)
    assert dt.to_python(now) == now
    assert dt.to_python(now.isoformat()) == now

    d = fields.DateField()
    today = datetime.date.today()
    assert d.to_python(today) == today
    assert d.to_python(today.isoformat()) == today

    t = fields.TimeField()
    now_t = datetime.datetime.now().time()
    assert t.to_python(now_t) == now_t
    assert t.to_python(now_t.isoformat()) == now_t


def test_binary_field():
    b = fields.BinaryField()
    assert b.to_python(b"123") == b"123"
    assert b.to_python("123") == b"123"
    assert b.to_db("123") == b"123"


def test_json_field():
    j = fields.JSONField()
    assert j.to_python('{"a": 1}') == {"a": 1}
    assert j.to_python({"a": 1}) == {"a": 1}
    assert j.to_db({"a": 1}) == '{"a": 1}'


def test_uuid_field():
    u = fields.UUIDField(auto=True)
    assert callable(u.default)

    val = uuid.uuid4()
    assert u.to_python(val) == val
    assert u.to_python(str(val)) == val
    assert u.to_db(val) == str(val)


def test_foreign_key_field():
    fk = fields.ForeignKey(to="auth.User")
    fk.name = "user"
    assert fk.column_name == "user_id"

    fk2 = fields.ForeignKey(to="auth.User", db_column="custom_fk")
    assert fk2.column_name == "custom_fk"


def test_email_field():
    email = fields.EmailField()
    email.name = "email"
    email.validate("test@test.com")
    with pytest.raises(ValueError, match="invalid email address"):
        email.validate("invalidemail")


def test_file_image_fields():
    f = fields.FileField()
    f.name = "doc"
    f._max_file_size = 100

    # string (already saved)
    f.validate("path/to/doc.pdf")

    # bytes
    f.validate(b"12345")
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        f.validate(b"1" * 101)

    img = fields.ImageField()
    img.name = "pic"
    img._max_file_size = 100
    img.validate("path/to/pic.png")

    with pytest.raises(ValueError, match="file extension '.txt' is not allowed"):
        img.validate("path/to/file.txt")

    # get_content_size
    class FakeFile:
        size = 50

    assert fields.FileField._get_content_size(FakeFile()) == 50

    import io

    io_file = io.BytesIO(b"abc")
    assert fields.FileField._get_content_size(io_file) == 3


def test_datetime_to_db_and_aware():

    dt_field = fields.DateTimeField()

    class MockSettings:
        USE_TZ = True

    with patch("openviper.db.fields.settings", MockSettings):
        naive = datetime.datetime(2023, 1, 1)
        datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC)

        # Test to_python timezone manipulation
        res = dt_field.to_python(naive)
        assert res.tzinfo is not None  # Made aware

        # Test to_db timezone manipulation
        db_res = dt_field.to_db(naive)
        assert db_res.tzinfo is datetime.UTC  # Converted to UTC


def test_foreign_key_column_name():
    class TestField(fields.Field):
        pass

    fk = fields.ForeignKey(to="auth.User")
    fk.name = "user"
    assert fk.column_name == "user_id"

    fk2 = fields.ForeignKey(to="auth.User", db_column="my_fk")
    assert fk2.column_name == "my_fk"


def test_onetoone_manytomany():
    o2o = fields.OneToOneField(to="auth.User")
    assert o2o.unique is True

    m2m = fields.ManyToManyField(to="auth.Role", through="auth.UserRole", related_name="users")
    assert m2m._column_type == ""
    assert m2m.through == "auth.UserRole"
    assert m2m.related_name == "users"


def test_auto_field():
    af = fields.AutoField()
    assert af.primary_key is True
    assert af.auto_increment is True
    assert af.to_python("5") == 5
    assert af.to_python(None) is None


def test_specialty_char_fields():
    # Slug, IP, URL
    slug = fields.SlugField()
    assert slug.max_length == 50

    ip = fields.IPAddressField()
    assert ip.max_length == 45

    url = fields.URLField()
    assert url.max_length == 2048


def test_file_field_null_validation():
    ff = fields.FileField(null=False)
    ff.name = "doc"
    with pytest.raises(ValueError, match="cannot be null"):
        ff.validate(None)

    ff_null = fields.FileField(null=True)
    ff_null.validate(None)  # Should pass without raising


def test_file_field_size_fallback():
    class MockSettingsMissing:
        pass

    with patch("openviper.db.fields.settings", MockSettingsMissing, create=True):
        ff = fields.FileField()
        assert ff.max_file_size == 10 * 1024 * 1024  # default fallback 10MB


def test_datetime_complex_timezone():

    dt_field = fields.DateTimeField()

    # local time naive => aware
    class MockSettings:
        USE_TZ = True

    with (
        patch("openviper.db.fields.settings", MockSettings),
        patch(
            "openviper.db.fields.timezone.get_current_timezone",
            return_value=datetime.timezone(-datetime.timedelta(hours=5)),
        ),
    ):
        # parse from string
        res = dt_field.to_python("2023-01-01T12:00:00")
        assert res.tzinfo is not None

        # db parse aware
        aware_t = datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC)
        db_res = dt_field.to_db(aware_t)
        assert db_res.tzinfo is datetime.UTC

        # db parse naive
        naive_t = datetime.datetime(2023, 1, 1)
        db_res_n = dt_field.to_db(naive_t)
        assert db_res_n.tzinfo is datetime.UTC

        db_from_str = dt_field.to_db("2023-01-01T12:00:00")
        assert db_from_str.tzinfo is datetime.UTC

    class MockSettingsFalse:
        USE_TZ = False

    with (
        patch("openviper.db.fields.settings", MockSettingsFalse),
        patch("openviper.db.fields.timezone.get_current_timezone", return_value=datetime.UTC),
    ):
        aware_t = datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC)
        assert dt_field.to_python(aware_t).tzinfo is None
        assert dt_field.to_db(aware_t).tzinfo is None

        naive_t = datetime.datetime(2023, 1, 1)
        assert dt_field.to_python(naive_t).tzinfo is None
        assert dt_field.to_db(naive_t).tzinfo is None


def test_uuid_none():
    u = fields.UUIDField()
    assert u.to_python(None) is None
    assert u.to_db(None) is None


def test_json_none():
    j = fields.JSONField()
    assert j.to_python(None) is None
    assert j.to_db(None) is None


def test_image_field_null_upload():
    img = fields.ImageField()
    img.validate(None)

    class UploadObj:
        filename = "test.jpg"

    img.validate(UploadObj())


def test_boolean_field_extra():
    b = fields.BooleanField()
    assert b.to_python(True) is True
    assert b.to_python("yes") is True
    assert b.to_python("on") is True
    assert b.to_python("1") is True
    assert b.to_python("false") is False


def test_date_time_extra():

    d = fields.DateField()
    t = fields.TimeField()

    assert d.to_python(None) is None
    dt_obj = datetime.date(2023, 1, 1)
    assert d.to_python(dt_obj) is dt_obj

    assert t.to_python(None) is None
    time_obj = datetime.time(12, 0)
    assert t.to_python(time_obj) is time_obj


def test_datetime_to_python_timezone_aware():
    from openviper.utils import timezone

    dt_field = fields.DateTimeField()

    class MockSettings:
        USE_TZ = True

    with patch("openviper.db.fields.settings", MockSettings):
        aware_dt = datetime.datetime(2023, 1, 1, tzinfo=timezone.get_current_timezone())
        res = dt_field.to_python(aware_dt)
        assert res.tzinfo is datetime.UTC  # converted to UTC


def test_file_field_max_file_size_error():
    class MissingSettings:
        pass

    with patch("openviper.db.fields.settings", MissingSettings):
        f = fields.FileField()
        assert f.max_file_size == 10485760  # 10MB fallback


def test_binary_field_types():
    b = fields.BinaryField()
    assert b.to_python(None) is None
    assert b.to_python([1, 2, 3]) == b"\x01\x02\x03"


def test_missing_line_coverage():
    b = fields.BooleanField()
    assert b.to_db(None) is None

    dt = fields.DateTimeField()
    assert dt.to_python(None) is None
    assert dt.to_db(None) is None

    class BadSettings:
        MAX_FILE_SIZE = "invalid_int"

    with patch("openviper.db.fields.settings", BadSettings):
        f = fields.FileField()
        assert f.max_file_size == 10485760



def test_foreign_key_resolve_target_branches():
    # callable target calls it and returns the resulting type
    class TargetModel:
        pass

    fk_callable = fields.ForeignKey(to=lambda: TargetModel)
    assert fk_callable.resolve_target() is TargetModel

    # non-string, non-type, non-callable target returns None
    fk_int = fields.ForeignKey(to=42)
    assert fk_int.resolve_target() is None

    # dotted string resolved via import_string to a callable returning a type
    def _getter():
        return TargetModel

    with patch("openviper.utils.import_string", return_value=_getter):
        fk_dotted = fields.ForeignKey(to="some.module.get_model")
        assert fk_dotted.resolve_target() is TargetModel


def test_foreign_key_resolve_target_registry_lookups():
    from openviper.db.models import Model, ModelMeta

    class SomeModel(Model):
        class Meta:
            table_name = "some_model_reg_test"

    SomeModel._app_name = "testpkg"

    # app_label prefix lookup
    ModelMeta.registry["testpkg.SomeModel"] = SomeModel

    class ParentModel(Model):
        class Meta:
            table_name = "parent_model_reg_test"

    ParentModel._app_name = "testpkg"

    fk_prefix = fields.ForeignKey(to="SomeModel")
    fk_prefix.model_class = ParentModel
    try:
        assert fk_prefix.resolve_target() is SomeModel
    finally:
        ModelMeta.registry.pop("testpkg.SomeModel", None)

    # brute-force name search — no dot in registry key
    ModelMeta.registry["SomeModel"] = SomeModel
    fk_direct = fields.ForeignKey(to="SomeModel")
    try:
        assert fk_direct.resolve_target() is SomeModel
    finally:
        ModelMeta.registry.pop("SomeModel", None)
