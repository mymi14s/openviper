"""Unit tests for openviper.exceptions.ModelNotFoundError and ModelCollisionError."""

from openviper.exceptions import ModelCollisionError, ModelNotFoundError


def test_model_not_found_error_attributes():
    err = ModelNotFoundError("foo", ["bar", "baz"])
    assert err.model == "foo"
    assert err.available == ["bar", "baz"]
    assert "foo" in str(err)
    assert "bar" in str(err)
    assert "baz" in str(err)


def test_model_not_found_error_no_available():
    err = ModelNotFoundError("foo")
    assert err.model == "foo"
    assert err.available == []
    assert "foo" in str(err)


def test_model_collision_error_attributes():
    err = ModelCollisionError("foo", "prov1", "prov2")
    assert err.model == "foo"
    assert err.existing_provider == "prov1"
    assert err.new_provider == "prov2"
    assert "foo" in str(err)
    assert "prov1" in str(err)
    assert "prov2" in str(err)
