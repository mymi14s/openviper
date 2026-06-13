"""Small async model factory system for OpenViper tests."""

import dataclasses
import itertools
import typing as t
from collections.abc import Awaitable, Callable

from openviper.auth.hashers import make_password, make_unusable_password
from openviper.auth.models import Permission, Role
from openviper.auth.utils import get_user_model
from openviper.db.models import Model


@dataclasses.dataclass(slots=True)
class Sequence:
    """Generate field values from an incrementing integer via ``itertools.count``."""

    callback: Callable[[int], object]
    counter: itertools.count = dataclasses.field(default_factory=itertools.count)

    def evaluate(self) -> object:
        value = self.callback(next(self.counter))
        return value


@dataclasses.dataclass(frozen=True, slots=True)
class LazyAttribute:
    """Generate a field value from already evaluated attributes."""

    callback: Callable[[dict[str, object]], object]

    def evaluate(self, attributes: dict[str, object]) -> object:
        return self.callback(attributes)


@dataclasses.dataclass(frozen=True, slots=True)
class RelatedFactory:
    """Build a related object from another factory."""

    factory: type[ModelFactory[Model]]
    defaults: dict[str, object] = dataclasses.field(default_factory=dict)

    def build(self, **overrides: object) -> Model:
        return self.factory.build(**{**self.defaults, **overrides})

    async def create(self, **overrides: object) -> Model:
        return await self.factory.create(**{**self.defaults, **overrides})


@dataclasses.dataclass(frozen=True, slots=True)
class PostGeneration:
    """Run a callback after factory build or create."""

    callback: Callable[[Model, bool], object | Awaitable[object]]


class ModelFactory[ModelT: Model]:
    """Base class for building and creating OpenViper model instances."""

    class Meta:
        model: type[Model] | None = None

    resolved_attrs: dict[str, object] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "Meta", None) is not None:
            cls.resolved_attrs = cls.resolve_attributes()

    @classmethod
    def iter_factory_classes(cls) -> t.Iterator[type]:
        """Yield non-base classes from the MRO in resolution order."""
        for klass in reversed(cls.mro()):
            if klass not in {ModelFactory, object}:
                yield klass

    @classmethod
    def resolve_attributes(cls) -> dict[str, object]:
        """Walk the MRO once and collect factory field descriptors."""
        attributes: dict[str, object] = {}
        for klass in cls.iter_factory_classes():
            for name, value in vars(klass).items():
                if name.startswith("_") or name in {"Meta", "resolved_attrs"} or callable(value):
                    continue
                if isinstance(value, (classmethod, staticmethod, PostGeneration)):
                    continue
                attributes[name] = value
        return attributes

    @classmethod
    def build(cls, **overrides: object) -> ModelT:
        model_class = cls.get_model_class()
        attributes = cls.build_attributes(overrides)
        return t.cast("ModelT", model_class(**attributes))

    @classmethod
    async def create(cls, **overrides: object) -> ModelT:
        instance = cls.build(**overrides)
        await instance.save(ignore_permissions=True)
        await cls.run_post_generation(instance, created=True)
        return instance

    @classmethod
    async def create_batch(cls, size: int, **overrides: object) -> list[ModelT]:
        return [await cls.create(**overrides) for _index in range(size)]

    @classmethod
    def build_batch(cls, size: int, **overrides: object) -> list[ModelT]:
        return [cls.build(**overrides) for _index in range(size)]

    @classmethod
    def get_model_class(cls) -> type[Model]:
        meta = getattr(cls, "Meta", None)
        model_class = getattr(meta, "model", None)
        if model_class is None:
            raise RuntimeError(f"{cls.__name__}.Meta.model must be set.")
        return t.cast("type[Model]", model_class)

    @classmethod
    def build_attributes(cls, overrides: dict[str, object]) -> dict[str, object]:
        resolved = cls.resolved_attrs
        attributes: dict[str, object] = {}
        for name, value in resolved.items():
            attributes[name] = evaluate_factory_value(value, attributes)
        attributes.update(overrides)
        return attributes

    @classmethod
    async def run_post_generation(cls, instance: Model, created: bool) -> None:
        for klass in cls.iter_factory_classes():
            for value in vars(klass).values():
                if isinstance(value, PostGeneration):
                    result = value.callback(instance, created)
                    if hasattr(result, "__await__"):
                        await t.cast("Awaitable[object]", result)


def evaluate_factory_value(value: object, attributes: dict[str, object]) -> object:
    if isinstance(value, Sequence):
        return value.evaluate()
    if isinstance(value, LazyAttribute):
        return value.evaluate(attributes)
    if isinstance(value, RelatedFactory):
        return value.build()
    return value


class UserFactory(ModelFactory[Model]):
    """Factory for the active user model (built-in or custom)."""

    class Meta:
        model = None

    username: object = Sequence(lambda n: f"user{n}")
    email: object = Sequence(lambda n: f"user{n}@example.com")
    first_name: object = "Test"
    last_name: object = "User"
    is_active: object = True
    is_staff: object = False
    is_superuser: object = False

    @classmethod
    def get_model_class(cls) -> type[Model]:
        return t.cast("type[Model]", get_user_model())

    @classmethod
    def build(cls, **overrides: object) -> Model:
        attributes = cls.build_attributes(overrides)
        attributes.pop("password", None)
        model_class = cls.get_model_class()
        instance = model_class(**t.cast("dict[str, object]", attributes))
        instance.password = make_unusable_password()
        return instance

    @classmethod
    async def create(cls, **overrides: object) -> Model:
        raw_password = t.cast("str", overrides.pop("password", "password"))
        instance = cls.build(**overrides)
        instance.password = await make_password(raw_password)
        await instance.save(ignore_permissions=True)
        await cls.run_post_generation(instance, created=True)
        return instance


class SuperuserFactory(UserFactory):
    """Factory that produces superuser accounts."""

    is_staff: object = True
    is_superuser: object = True
    username: object = Sequence(lambda n: f"admin{n}")
    email: object = Sequence(lambda n: f"admin{n}@example.com")


class PermissionFactory(ModelFactory[Permission]):
    """Factory for Permission records."""

    class Meta:
        model = Permission

    codename: object = Sequence(lambda n: f"perm_{n}")
    name: object = Sequence(lambda n: f"Permission {n}")


class RoleFactory(ModelFactory[Role]):
    """Factory for Role records."""

    class Meta:
        model = Role

    name: object = Sequence(lambda n: f"role_{n}")
    description: object = "Test role"
