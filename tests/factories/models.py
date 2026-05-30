from typing import TypeVar

from openviper.db.models import Model

T = TypeVar("T", bound=Model)


async def create_instance[T: Model](model_class: type[T], **kwargs: object) -> T:
    """Create and save a model instance for testing."""
    instance = model_class(**kwargs)
    await instance.save()
    return instance


def build_instance[T: Model](model_class: type[T], **kwargs: object) -> T:
    """Build a model instance without saving it to the database."""
    return model_class(**kwargs)
