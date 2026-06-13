"""Relationship traversal helpers - imported by executor and models to break circular deps."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.db.fields import ForeignKey, OneToOneField
from openviper.exceptions import FieldError

if TYPE_CHECKING:
    from openviper.db.fields import Field
    from openviper.db.models import Model


class TraversalStep:
    """Represents one step in a relationship traversal chain."""

    __slots__ = ("field_name", "field", "model_cls", "is_relation")

    def __init__(
        self, field_name: str, field: Field, model_cls: type[Model], is_relation: bool = False
    ) -> None:
        self.field_name = field_name
        self.field = field
        self.model_cls = model_cls
        self.is_relation = is_relation

    def __repr__(self) -> str:
        return f"Step({self.field_name}: {self.model_cls.__name__})"


class TraversalLookup:
    """Parses and validates relationship traversal in filter lookups.

    Parses filter keys like "author__username" or "author__hobby__description"
    and validates the entire chain is valid, returning steps for JOIN construction.

    A maximum traversal depth of 5 FK hops is enforced to prevent query
    complexity attacks that could exhaust memory via deep JOIN chains.
    """

    __slots__ = ("key", "model_cls", "parts", "final_field", "final_model")

    MAX_TRAVERSAL_DEPTH = 5

    def __init__(self, key: str, model_cls: type) -> None:
        self.key = key
        self.model_cls = model_cls
        self.parts: list[TraversalStep] = []
        self.final_field: Field | None = None
        self.final_model: type[Model] | None = None
        self.parse()

    def parse(self) -> None:
        """Parse and validate the traversal path."""
        parts = self.key.split("__")
        current_model = self.model_cls
        current_steps = []

        fk_depth = len(parts) - 1
        if fk_depth > self.MAX_TRAVERSAL_DEPTH:
            raise FieldError(
                f"Traversal depth {fk_depth} exceeds maximum of "
                f"{self.MAX_TRAVERSAL_DEPTH} for '{self.key}'"
            )

        for _i, part in enumerate(parts[:-1]):
            if not hasattr(current_model, "_fields"):
                raise FieldError(f"Cannot traverse through {current_model.__name__}: not a Model")

            field = current_model._fields.get(part)
            if field is None:
                raise FieldError(f"Field '{part}' not found on {current_model.__name__}")

            if not isinstance(field, (ForeignKey, OneToOneField)):
                raise FieldError(
                    f"Cannot traverse through non-relationship field '{part}' "
                    f"(type: {type(field).__name__}) on {current_model.__name__}"
                )

            target_model = field.resolve_target()
            if target_model is None:
                raise FieldError(
                    f"Cannot resolve target model for field '{part}' on {current_model.__name__}"
                )

            current_steps.append(TraversalStep(part, field, current_model, is_relation=True))
            current_model = target_model

        if not hasattr(current_model, "_fields"):
            raise FieldError(f"Cannot access field on {current_model.__name__}: not a Model")

        final_field_name = parts[-1]
        final_field = current_model._fields.get(final_field_name)
        if final_field is None:
            raise FieldError(f"Field '{final_field_name}' not found on {current_model.__name__}")

        current_steps.append(
            TraversalStep(final_field_name, final_field, current_model, is_relation=False)
        )

        self.parts = current_steps
        self.final_field = final_field
        self.final_model = current_model

    def is_simple_field(self) -> bool:
        """Check if this is a simple field lookup (no FK traversal)."""
        return len(self.parts) == 1

    def get_joins_needed(self) -> list[TraversalStep]:
        """Return the FK traversal steps (all but the final field)."""
        return self.parts[:-1]

    def __repr__(self) -> str:
        return f"TraversalLookup({self.key})"
