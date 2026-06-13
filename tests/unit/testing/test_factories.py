"""Tests for OpenViper model factories."""

from __future__ import annotations

import pytest

from openviper.db.fields import CharField
from openviper.db.models import Model
from openviper.testing.factories import (
    LazyAttribute,
    ModelFactory,
    PostGeneration,
    RelatedFactory,
    Sequence,
    evaluate_factory_value,
)


class FactoryUser(Model):
    email = CharField(max_length=120)
    name = CharField(max_length=120)

    class Meta:
        table_name = "factory_users"


class FactoryProfile(Model):
    bio = CharField(max_length=255)

    class Meta:
        table_name = "factory_profiles"


class UserFactory(ModelFactory[FactoryUser]):
    class Meta:
        model = FactoryUser

    email = Sequence(lambda index: f"user{index}@example.com")
    name = LazyAttribute(lambda values: str(values["email"]).split("@")[0])


class ProfileFactory(ModelFactory[FactoryProfile]):
    class Meta:
        model = FactoryProfile

    bio = "Default bio"


# ── build ─────────────────────────────────────────────────────────────────


def test_model_factory_builds_model_instance() -> None:
    user = UserFactory.build()

    assert isinstance(user, FactoryUser)
    assert user.email == "user0@example.com"
    assert user.name == "user0"


def test_model_factory_allows_field_overrides() -> None:
    user = UserFactory.build(email="custom@example.com")

    assert user.email == "custom@example.com"


def test_model_factory_sequence_increments_across_builds() -> None:
    class SeqFactory(ModelFactory[FactoryUser]):
        class Meta:
            model = FactoryUser

        email = Sequence(lambda n: f"seq{n}@example.com")
        name = "Fixed"

    first = SeqFactory.build()
    second = SeqFactory.build()

    assert first.email != second.email


def test_model_factory_lazy_attribute_receives_evaluated_fields() -> None:
    user = UserFactory.build()

    # LazyAttribute for name should be derived from the evaluated email value.
    assert user.name == user.email.split("@")[0]


# ── build_batch ───────────────────────────────────────────────────────────


def test_model_factory_build_batch_returns_correct_count() -> None:
    users = UserFactory.build_batch(3)

    assert len(users) == 3
    assert all(isinstance(u, FactoryUser) for u in users)


def test_model_factory_build_batch_of_zero_returns_empty_list() -> None:
    result = UserFactory.build_batch(0)

    assert result == []


# ── RelatedFactory ────────────────────────────────────────────────────────


def test_related_factory_build_returns_related_instance() -> None:
    related = RelatedFactory(ProfileFactory)

    profile = related.build()

    assert isinstance(profile, FactoryProfile)
    assert profile.bio == "Default bio"


def test_related_factory_build_accepts_default_overrides() -> None:
    related = RelatedFactory(ProfileFactory, defaults={"bio": "Custom bio"})

    profile = related.build()

    assert profile.bio == "Custom bio"


# ── PostGeneration ────────────────────────────────────────────────────────


def test_post_generation_callback_is_stored() -> None:
    sentinel: list[str] = []

    def on_create(instance: object, created: bool) -> None:
        sentinel.append("called")

    pg = PostGeneration(callback=on_create)

    assert pg.callback is on_create


# ── get_model_class ───────────────────────────────────────────────────────


def test_model_factory_raises_when_meta_model_isunset() -> None:
    class BrokenFactory(ModelFactory[FactoryUser]):
        class Meta:
            model = None

    with pytest.raises(RuntimeError, match="Meta.model"):
        BrokenFactory.get_model_class()


# ── evaluate_factory_value ────────────────────────────────────────────────


def test_evaluate_factory_value_returns_plain_values_unchanged() -> None:
    assert evaluate_factory_value("hello", {}) == "hello"
    assert evaluate_factory_value(42, {}) == 42
    assert evaluate_factory_value(None, {}) is None


def test_evaluate_factory_value_calls_sequence() -> None:
    seq = Sequence(lambda n: n * 10)

    first = evaluate_factory_value(seq, {})
    second = evaluate_factory_value(seq, {})

    assert first == 0
    assert second == 10


def test_evaluate_factory_value_calls_lazy_attribute_with_attributes() -> None:
    lazy = LazyAttribute(lambda attrs: str(attrs.get("x", "")) + "_lazy")

    result = evaluate_factory_value(lazy, {"x": "value"})

    assert result == "value_lazy"


def test_evaluate_factory_value_builds_related_factory() -> None:
    related = RelatedFactory(ProfileFactory)

    result = evaluate_factory_value(related, {})

    assert isinstance(result, FactoryProfile)


# ── iter_factory_classes ─────────────────────────────────────────────────


def test_iter_factory_classes_yields_non_base_classes() -> None:
    classes = list(UserFactory.iter_factory_classes())

    assert ModelFactory not in classes
    assert object not in classes
    assert UserFactory in classes


def test_iter_factory_classes_includes_intermediate_subclasses() -> None:

    class MiddleFactory(ModelFactory[FactoryUser]):
        class Meta:
            model = FactoryUser

        middle_field: object = "middle"

    class LeafFactory(MiddleFactory):
        class Meta:
            model = FactoryUser

        leaf_field: object = "leaf"

    classes = list(LeafFactory.iter_factory_classes())

    assert MiddleFactory in classes
    assert LeafFactory in classes
