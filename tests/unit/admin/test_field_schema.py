from openviper.admin.fields import get_field_schema
from openviper.db.fields import CharField, DateField, DateTimeField, ForeignKey, IntegerField
from openviper.db.models import Model


def test_char_field_with_choices_schema():
    field = CharField(choices=[("a", "Alpha"), ("b", "Beta")])
    field.name = "status"
    schema = get_field_schema(field)

    assert schema["component"] == "select"
    assert "choices" in schema["config"]
    assert schema["config"]["choices"] == [
        {"value": "a", "label": "Alpha"},
        {"value": "b", "label": "Beta"},
    ]


def test_date_and_datetime_schema():
    date_field = DateField()
    date_field.name = "birthday"
    date_schema = get_field_schema(date_field)
    assert date_schema["component"] == "date"

    dt_field = DateTimeField()
    dt_field.name = "created_at"
    dt_schema = get_field_schema(dt_field)
    assert dt_schema["component"] == "datetime"


def test_foreign_key_schema():
    class OtherModel(Model):
        pass

    field = ForeignKey(OtherModel)
    field.name = "other"
    schema = get_field_schema(field)

    assert schema["component"] == "foreignkey"
    assert schema["config"]["searchable"] is True
    assert schema["config"]["filterable"] is True


def test_primary_key_schema():
    field = IntegerField(primary_key=True)
    field.name = "id"
    schema = get_field_schema(field)

    assert schema["config"]["filterable"] is True


def test_get_field_component_type_logic():
    from openviper.admin.fields import get_field_component_type

    assert get_field_component_type(CharField(choices=[(1, "1")])) == "select"
    assert get_field_component_type(DateField()) == "date"
    assert get_field_component_type(DateTimeField()) == "datetime"
    assert get_field_component_type(ForeignKey(Model)) == "foreignkey"
    assert get_field_component_type(CharField()) == "text"
