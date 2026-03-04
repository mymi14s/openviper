import pytest

from openviper.db import fields
from openviper.db.models import Model


class User(Model):
    class Meta:
        table_name = "custom_users"

    username = fields.CharField(max_length=50)
    age = fields.IntegerField(null=True)


class Post(Model):
    title = fields.CharField(max_length=100)


def test_model_meta_table_name():
    assert User._table_name == "custom_users"
    # Post is defined in tests.integration.db.test_db_models → app_name = "db"
    # Auto-generated table name: db_post
    assert Post._table_name == "db_post"


def test_model_init_fields():
    user = User(username="alice", age=30, extra="metadata")
    assert user.username == "alice"
    assert user.age == 30
    assert user.extra == "metadata"


def test_model_snapshot_and_changes():
    user = User(username="alice", age=30)
    assert user.has_changed is False

    user.username = "bob"
    assert user.has_changed is True
    assert user._get_changed_fields() == {"username": "alice"}


@pytest.mark.asyncio
async def test_model_validation():
    user = User(username="a" * 51)  # max_length=50
    with pytest.raises(ValueError, match="exceeds max_length"):
        await user.validate()

    user.username = "alice"
    await user.validate()  # Should pass
