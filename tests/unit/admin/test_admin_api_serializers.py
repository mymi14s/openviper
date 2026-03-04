"""Unit tests for openviper.admin.api.serializers."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.api.serializers import (
    ModelDetailSerializer,
    ModelListSerializer,
    serialize_field_info,
    serialize_for_detail,
    serialize_for_list,
    serialize_instance,
    serialize_model_info,
    serialize_value,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_instance(fields: dict, field_values: dict, pk: int = 1):
    """Return a plain Python object that looks like a model instance.

    Uses ``type()`` so that ``instance.__class__._fields`` resolves correctly
    without modifying the MagicMock class itself.
    """
    FakeModel = type("FakeModel", (), {"_fields": fields})
    obj = FakeModel()
    obj.id = pk
    for name, value in field_values.items():
        setattr(obj, name, value)
    return obj


def _make_model_admin(list_display=None, model_info=None):
    model_admin = MagicMock()
    model_admin.get_list_display.return_value = list_display or []
    if model_info is not None:
        model_admin.get_model_info.return_value = model_info
    return model_admin


# ---------------------------------------------------------------------------
# serialize_value — None
# ---------------------------------------------------------------------------


class TestSerializeValueNone:
    def test_none_returns_none(self):
        assert serialize_value(None) is None


# ---------------------------------------------------------------------------
# serialize_value — datetime-like (hasattr isoformat)
# ---------------------------------------------------------------------------


class TestSerializeValueDatetimeLike:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 12, 30, 45)
        assert serialize_value(dt) == dt.isoformat()

    def test_date(self):
        d = date(2024, 3, 10)
        assert serialize_value(d) == d.isoformat()

    def test_time(self):
        t = time(8, 45, 0)
        assert serialize_value(t) == t.isoformat()

    def test_custom_object_with_isoformat(self):
        class FakeDate:
            def isoformat(self):
                return "fake-iso"

        assert serialize_value(FakeDate()) == "fake-iso"


# ---------------------------------------------------------------------------
# serialize_value — basic scalar types
# ---------------------------------------------------------------------------


class TestSerializeValueScalars:
    def test_string(self):
        assert serialize_value("hello") == "hello"

    def test_empty_string(self):
        assert serialize_value("") == ""

    def test_integer(self):
        assert serialize_value(42) == 42

    def test_zero(self):
        assert serialize_value(0) == 0

    def test_negative_integer(self):
        assert serialize_value(-7) == -7

    def test_float(self):
        assert serialize_value(3.14) == 3.14

    def test_bool_true(self):
        result = serialize_value(True)
        assert result is True

    def test_bool_false(self):
        result = serialize_value(False)
        assert result is False


# ---------------------------------------------------------------------------
# serialize_value — collections
# ---------------------------------------------------------------------------


class TestSerializeValueCollections:
    def test_list_of_scalars(self):
        assert serialize_value([1, "two", None]) == [1, "two", None]

    def test_tuple_becomes_list(self):
        result = serialize_value((10, 20, 30))
        assert result == [10, 20, 30]
        assert isinstance(result, list)

    def test_nested_list(self):
        assert serialize_value([[1, 2], [3, 4]]) == [[1, 2], [3, 4]]

    def test_list_with_datetime(self):
        dt = datetime(2024, 6, 1, 0, 0, 0)
        result = serialize_value([dt, 42])
        assert result == [dt.isoformat(), 42]

    def test_tuple_with_none(self):
        assert serialize_value((None, None)) == [None, None]

    def test_dict_basic(self):
        assert serialize_value({"a": 1, "b": "two"}) == {"a": 1, "b": "two"}

    def test_dict_with_none_values(self):
        assert serialize_value({"key": None}) == {"key": None}

    def test_nested_dict(self):
        result = serialize_value({"outer": {"inner": 42}})
        assert result == {"outer": {"inner": 42}}

    def test_dict_with_datetime_value(self):
        dt = datetime(2024, 1, 1)
        result = serialize_value({"ts": dt})
        assert result == {"ts": dt.isoformat()}

    def test_empty_list(self):
        assert serialize_value([]) == []

    def test_empty_dict(self):
        assert serialize_value({}) == {}

    def test_empty_tuple(self):
        assert serialize_value(()) == []


# ---------------------------------------------------------------------------
# serialize_value — UUID (hasattr hex)
# ---------------------------------------------------------------------------


class TestSerializeValueUUID:
    def test_uuid_returns_string(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = serialize_value(u)
        assert result == str(u)
        assert isinstance(result, str)

    def test_uuid4_round_trip(self):
        u = uuid.uuid4()
        assert serialize_value(u) == str(u)


# ---------------------------------------------------------------------------
# serialize_value — Decimal (hasattr as_tuple)
# ---------------------------------------------------------------------------


class TestSerializeValueDecimal:
    def test_decimal_returns_float(self):
        d = Decimal("12.34")
        result = serialize_value(d)
        assert isinstance(result, float)
        assert result == float(d)

    def test_decimal_zero(self):
        assert serialize_value(Decimal("0")) == 0.0

    def test_decimal_negative(self):
        d = Decimal("-3.14")
        assert serialize_value(d) == float(d)


# ---------------------------------------------------------------------------
# serialize_value — fallback
# ---------------------------------------------------------------------------


class TestSerializeValueFallback:
    def test_custom_object_falls_back_to_str(self):
        class Blob:
            def __str__(self):
                return "blob_repr"

        assert serialize_value(Blob()) == "blob_repr"

    def test_object_without_any_special_attributes(self):
        class Plain:
            pass

        obj = Plain()
        result = serialize_value(obj)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# serialize_instance
# ---------------------------------------------------------------------------


class TestSerializeInstance:
    def test_basic_fields_serialized(self):
        instance = _make_model_instance(
            fields={"name": MagicMock(), "age": MagicMock()},
            field_values={"name": "Alice", "age": 30},
            pk=1,
        )
        result = serialize_instance(instance, MagicMock())
        assert result == {"id": 1, "name": "Alice", "age": 30}

    def test_id_included_in_result(self):
        instance = _make_model_instance(fields={}, field_values={}, pk=99)
        result = serialize_instance(instance, MagicMock())
        assert result["id"] == 99

    def test_id_missing_returns_none(self):
        """When instance has no `id` attribute, getattr returns None."""

        class NoIdModel:
            _fields = {}

        obj = NoIdModel()
        result = serialize_instance(obj, MagicMock())
        assert result["id"] is None

    def test_include_fields_filters_output(self):
        instance = _make_model_instance(
            fields={"name": MagicMock(), "age": MagicMock(), "email": MagicMock()},
            field_values={"name": "Bob", "age": 25, "email": "b@example.com"},
            pk=2,
        )
        result = serialize_instance(instance, MagicMock(), include_fields=["name"])
        assert "name" in result
        assert "age" not in result
        assert "email" not in result

    def test_include_fields_empty_list(self):
        instance = _make_model_instance(
            fields={"name": MagicMock()},
            field_values={"name": "Carol"},
            pk=3,
        )
        # Empty list means no fields (falsy -> use fields.keys() which is empty)
        # Actually: `include_fields or list(fields.keys())` — empty list is falsy,
        # so it falls through to list(fields.keys()).  This means all fields are included.
        result = serialize_instance(instance, MagicMock(), include_fields=[])
        assert "name" in result

    def test_none_field_value_serialized_as_none(self):
        instance = _make_model_instance(
            fields={"title": MagicMock()},
            field_values={"title": None},
            pk=4,
        )
        assert serialize_instance(instance, MagicMock())["title"] is None

    def test_datetime_field_value_isoformatted(self):
        dt = datetime(2024, 7, 4, 12, 0, 0)
        instance = _make_model_instance(
            fields={"created": MagicMock()},
            field_values={"created": dt},
            pk=5,
        )
        assert serialize_instance(instance, MagicMock())["created"] == dt.isoformat()

    def test_no_fields_returns_id_only(self):
        instance = _make_model_instance(fields={}, field_values={}, pk=10)
        result = serialize_instance(instance, MagicMock())
        assert result == {"id": 10}

    def test_model_admin_not_called_directly(self):
        """serialize_instance does not invoke model_admin methods itself."""
        model_admin = MagicMock()
        instance = _make_model_instance(fields={}, field_values={}, pk=1)
        serialize_instance(instance, model_admin)
        model_admin.get_list_display.assert_not_called()

    def test_uuid_field_value_serialized_to_string(self):
        u = uuid.uuid4()
        instance = _make_model_instance(
            fields={"uid": MagicMock()},
            field_values={"uid": u},
            pk=6,
        )
        assert serialize_instance(instance, MagicMock())["uid"] == str(u)

    def test_decimal_field_value_serialized_to_float(self):
        d = Decimal("9.99")
        instance = _make_model_instance(
            fields={"price": MagicMock()},
            field_values={"price": d},
            pk=7,
        )
        result = serialize_instance(instance, MagicMock())
        assert result["price"] == float(d)


# ---------------------------------------------------------------------------
# serialize_for_list
# ---------------------------------------------------------------------------


class TestSerializeForList:
    def test_basic_list_serialization(self):
        instance = MagicMock()
        instance.id = 10
        instance.name = "Dave"
        instance.status = "active"

        model_admin = _make_model_admin(list_display=["name", "status"])
        result = serialize_for_list(instance, model_admin)

        assert result == {"id": 10, "name": "Dave", "status": "active"}
        model_admin.get_list_display.assert_called_once()

    def test_empty_list_display_returns_id_only(self):
        instance = MagicMock()
        instance.id = 5
        model_admin = _make_model_admin(list_display=[])
        result = serialize_for_list(instance, model_admin)
        assert result == {"id": 5}

    def test_field_with_none_value(self):
        instance = MagicMock()
        instance.id = 1
        instance.title = None
        model_admin = _make_model_admin(list_display=["title"])
        result = serialize_for_list(instance, model_admin)
        assert result["title"] is None

    def test_field_with_datetime_value(self):
        dt = datetime(2024, 6, 15, 10, 0, 0)
        instance = MagicMock()
        instance.id = 2
        instance.created_at = dt
        model_admin = _make_model_admin(list_display=["created_at"])
        result = serialize_for_list(instance, model_admin)
        assert result["created_at"] == dt.isoformat()

    def test_missing_field_on_instance_returns_none(self):
        """Fields listed in list_display but absent on the instance default to None."""

        class BarebonesInstance:
            id = 3

        model_admin = _make_model_admin(list_display=["nonexistent"])
        result = serialize_for_list(BarebonesInstance(), model_admin)
        assert result["nonexistent"] is None

    def test_multiple_instances_independence(self):
        """Calling serialize_for_list twice produces independent results."""
        model_admin = _make_model_admin(list_display=["score"])

        inst1 = MagicMock()
        inst1.id = 1
        inst1.score = 100

        inst2 = MagicMock()
        inst2.id = 2
        inst2.score = 200

        r1 = serialize_for_list(inst1, model_admin)
        r2 = serialize_for_list(inst2, model_admin)
        assert r1["score"] == 100
        assert r2["score"] == 200

    def test_uuid_in_list_display(self):
        u = uuid.uuid4()
        instance = MagicMock()
        instance.id = 9
        instance.uid = u
        model_admin = _make_model_admin(list_display=["uid"])
        result = serialize_for_list(instance, model_admin)
        assert result["uid"] == str(u)


# ---------------------------------------------------------------------------
# serialize_for_detail
# ---------------------------------------------------------------------------


class TestSerializeForDetail:
    def test_basic_detail_serialization(self):
        instance = _make_model_instance(
            fields={"title": MagicMock(), "count": MagicMock()},
            field_values={"title": "Test", "count": 42},
            pk=7,
        )
        result = serialize_for_detail(instance, MagicMock())
        assert result == {"id": 7, "title": "Test", "count": 42}

    def test_no_fields_returns_id_only(self):
        instance = _make_model_instance(fields={}, field_values={}, pk=3)
        result = serialize_for_detail(instance, MagicMock())
        assert result == {"id": 3}

    def test_id_included(self):
        instance = _make_model_instance(
            fields={"name": MagicMock()},
            field_values={"name": "Eve"},
            pk=11,
        )
        assert serialize_for_detail(instance, MagicMock())["id"] == 11

    def test_uuid_field_serialized_to_string(self):
        u = uuid.uuid4()
        instance = _make_model_instance(
            fields={"uid": MagicMock()},
            field_values={"uid": u},
            pk=8,
        )
        assert serialize_for_detail(instance, MagicMock())["uid"] == str(u)

    def test_decimal_field_serialized_to_float(self):
        d = Decimal("4.99")
        instance = _make_model_instance(
            fields={"price": MagicMock()},
            field_values={"price": d},
            pk=9,
        )
        result = serialize_for_detail(instance, MagicMock())
        assert result["price"] == float(d)

    def test_datetime_field_serialized_to_iso(self):
        dt = datetime(2023, 12, 25, 0, 0, 0)
        instance = _make_model_instance(
            fields={"created": MagicMock()},
            field_values={"created": dt},
            pk=10,
        )
        assert serialize_for_detail(instance, MagicMock())["created"] == dt.isoformat()

    def test_model_admin_not_invoked(self):
        """serialize_for_detail should not call model_admin methods."""
        model_admin = MagicMock()
        instance = _make_model_instance(fields={}, field_values={}, pk=1)
        serialize_for_detail(instance, model_admin)
        model_admin.get_list_display.assert_not_called()
        model_admin.get_model_info.assert_not_called()

    def test_none_field_value_serialized_as_none(self):
        instance = _make_model_instance(
            fields={"optional": MagicMock()},
            field_values={"optional": None},
            pk=5,
        )
        assert serialize_for_detail(instance, MagicMock())["optional"] is None

    def test_multiple_fields_all_included(self):
        fields = {f"f{i}": MagicMock() for i in range(5)}
        values = {f"f{i}": i * 10 for i in range(5)}
        instance = _make_model_instance(fields=fields, field_values=values, pk=20)
        result = serialize_for_detail(instance, MagicMock())
        for i in range(5):
            assert result[f"f{i}"] == i * 10


# ---------------------------------------------------------------------------
# serialize_model_info
# ---------------------------------------------------------------------------


class TestSerializeModelInfo:
    def test_delegates_to_get_model_info(self):
        expected = {"model": "Product", "app": "shop"}
        model_admin = _make_model_admin(model_info=expected)
        result = serialize_model_info(model_admin)
        assert result == expected
        model_admin.get_model_info.assert_called_once()

    def test_returns_whatever_get_model_info_returns(self):
        model_admin = MagicMock()
        model_admin.get_model_info.return_value = {"verbose_name": "Order"}
        assert serialize_model_info(model_admin) == {"verbose_name": "Order"}


# ---------------------------------------------------------------------------
# serialize_field_info
# ---------------------------------------------------------------------------


class TestSerializeFieldInfo:
    def test_delegates_to_get_field_schema(self):
        field = MagicMock()
        expected = {"name": "title", "type": "CharField"}
        with patch(
            "openviper.admin.api.serializers.get_field_schema", return_value=expected
        ) as mock_schema:
            result = serialize_field_info(field)
            mock_schema.assert_called_once_with(field)
            assert result == expected

    def test_passes_field_object_through(self):
        field = MagicMock()
        with patch(
            "openviper.admin.api.serializers.get_field_schema", return_value={}
        ) as mock_schema:
            serialize_field_info(field)
            args, _ = mock_schema.call_args
            assert args[0] is field


# ---------------------------------------------------------------------------
# ModelListSerializer
# ---------------------------------------------------------------------------


class TestModelListSerializer:
    def test_construction_stores_model_admin(self):
        model_admin = MagicMock()
        serializer = ModelListSerializer(model_admin)
        assert serializer.model_admin is model_admin

    def test_serialize_empty_list(self):
        model_admin = _make_model_admin(list_display=["name"])
        serializer = ModelListSerializer(model_admin)
        assert serializer.serialize([]) == []

    def test_serialize_single_instance(self):
        instance = MagicMock()
        instance.id = 1
        instance.name = "Alice"

        model_admin = _make_model_admin(list_display=["name"])
        serializer = ModelListSerializer(model_admin)
        result = serializer.serialize([instance])

        assert len(result) == 1
        assert result[0] == {"id": 1, "name": "Alice"}

    def test_serialize_multiple_instances(self):
        instances = []
        for i in range(4):
            inst = MagicMock()
            inst.id = i
            inst.score = i * 5
            instances.append(inst)

        model_admin = _make_model_admin(list_display=["score"])
        serializer = ModelListSerializer(model_admin)
        result = serializer.serialize(instances)

        assert len(result) == 4
        for i, item in enumerate(result):
            assert item["id"] == i
            assert item["score"] == i * 5

    def test_serialize_returns_list(self):
        model_admin = _make_model_admin(list_display=[])
        serializer = ModelListSerializer(model_admin)
        assert isinstance(serializer.serialize([]), list)

    def test_serialize_calls_serialize_for_list_for_each(self):
        """Each item in the output corresponds to one serialize_for_list call."""
        instances = [MagicMock() for _ in range(3)]
        for idx, inst in enumerate(instances):
            inst.id = idx

        model_admin = _make_model_admin(list_display=["id"])
        serializer = ModelListSerializer(model_admin)
        result = serializer.serialize(instances)
        assert len(result) == 3

    def test_serialize_with_datetime_field(self):
        dt = datetime(2025, 1, 1, 0, 0, 0)
        instance = MagicMock()
        instance.id = 99
        instance.ts = dt

        model_admin = _make_model_admin(list_display=["ts"])
        serializer = ModelListSerializer(model_admin)
        result = serializer.serialize([instance])
        assert result[0]["ts"] == dt.isoformat()


# ---------------------------------------------------------------------------
# ModelDetailSerializer
# ---------------------------------------------------------------------------


class TestModelDetailSerializer:
    def test_construction_stores_model_admin(self):
        model_admin = MagicMock()
        assert ModelDetailSerializer(model_admin).model_admin is model_admin

    def test_serialize_with_fields(self):
        instance = _make_model_instance(
            fields={"name": MagicMock(), "email": MagicMock()},
            field_values={"name": "Carol", "email": "carol@example.com"},
            pk=42,
        )
        serializer = ModelDetailSerializer(MagicMock())
        result = serializer.serialize(instance)
        assert result["id"] == 42
        assert result["name"] == "Carol"
        assert result["email"] == "carol@example.com"

    def test_serialize_no_fields_returns_id(self):
        instance = _make_model_instance(fields={}, field_values={}, pk=99)
        result = ModelDetailSerializer(MagicMock()).serialize(instance)
        assert result == {"id": 99}

    def test_serialize_returns_dict(self):
        instance = _make_model_instance(fields={}, field_values={}, pk=1)
        result = ModelDetailSerializer(MagicMock()).serialize(instance)
        assert isinstance(result, dict)

    def test_serialize_with_uuid_field(self):
        u = uuid.uuid4()
        instance = _make_model_instance(
            fields={"uid": MagicMock()},
            field_values={"uid": u},
            pk=55,
        )
        result = ModelDetailSerializer(MagicMock()).serialize(instance)
        assert result["uid"] == str(u)

    def test_serialize_with_decimal_field(self):
        d = Decimal("19.95")
        instance = _make_model_instance(
            fields={"price": MagicMock()},
            field_values={"price": d},
            pk=56,
        )
        result = ModelDetailSerializer(MagicMock()).serialize(instance)
        assert result["price"] == float(d)

    def test_serialize_with_datetime_field(self):
        dt = datetime(2024, 11, 11, 11, 11, 11)
        instance = _make_model_instance(
            fields={"updated": MagicMock()},
            field_values={"updated": dt},
            pk=57,
        )
        result = ModelDetailSerializer(MagicMock()).serialize(instance)
        assert result["updated"] == dt.isoformat()

    def test_serialize_delegates_to_serialize_for_detail(self):
        """ModelDetailSerializer.serialize calls serialize_for_detail internally."""
        instance = _make_model_instance(
            fields={"x": MagicMock()},
            field_values={"x": 7},
            pk=1,
        )
        model_admin = MagicMock()
        with patch(
            "openviper.admin.api.serializers.serialize_for_detail",
            return_value={"id": 1, "x": 7},
        ) as mock_sfd:
            serializer = ModelDetailSerializer(model_admin)
            result = serializer.serialize(instance)
            mock_sfd.assert_called_once_with(instance, model_admin)
            assert result == {"id": 1, "x": 7}
