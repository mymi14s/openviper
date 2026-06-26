"""Shared model-to-state building functions.

Extracted to avoid circular imports between detect.py and writer.py.
"""

from __future__ import annotations

import typing as t

from openviper.db.fields import CheckConstraint, ForeignKey, UniqueConstraint

if t.TYPE_CHECKING:
    from openviper.db.models import Model


def build_model_indexes(model_cls: type[Model]) -> list[dict[str, t.Any]]:
    """Build the list of indexes a model should have, including FK indexes."""
    indexes: list[dict[str, t.Any]] = []
    for idx in getattr(model_cls, "_meta_indexes", []):
        col_names = [
            model_cls._fields[f].column_name if f in model_cls._fields else f for f in idx.fields
        ]
        index_name = idx.name or f"idx_{model_cls._table_name}_{'_'.join(col_names)}"
        indexes.append({"name": index_name, "fields": col_names})
    for field in model_cls._fields.values():
        if not field.db_index or field.unique or field.primary_key:
            continue
        col_name = field.column_name
        idx_name = f"idx_{model_cls._table_name}_{col_name}"
        indexes.append({"name": idx_name, "fields": [col_name]})
    for field in model_cls._fields.values():
        if not isinstance(field, ForeignKey):
            continue
        col_name = field.column_name
        idx_name = f"idx_{model_cls._table_name}_{col_name}"
        if not any(i["name"] == idx_name for i in indexes):
            indexes.append({"name": idx_name, "fields": [col_name]})
    indexes.sort(key=lambda x: x.get("name") or str(x.get("fields")))
    return indexes


def build_model_constraints(model_cls: type[Model]) -> list[dict[str, t.Any]]:
    """Build the list of constraints declared in Meta.constraints."""
    constraints: list[dict[str, t.Any]] = []
    for constraint in getattr(model_cls, "_meta_constraints", []):
        if isinstance(constraint, CheckConstraint):
            constraints.append({
                "name": constraint.name,
                "type": "CHECK",
                "check": constraint.check,
            })
        elif isinstance(constraint, UniqueConstraint):
            col_names = [
                model_cls._fields[f].column_name if f in model_cls._fields else f
                for f in constraint.fields
            ]
            entry: dict[str, t.Any] = {
                "name": constraint.name,
                "type": "UNIQUE",
                "fields": col_names,
            }
            if constraint.condition:
                entry["condition"] = constraint.condition
            constraints.append(entry)
    constraints.sort(key=lambda c: c["name"])
    return constraints


def build_model_unique_together(model_cls: type[Model]) -> list[list[str]]:
    """Build the sorted unique_together lists from Meta.unique_together."""
    unique_together = [
        sorted(model_cls._fields[f].column_name if f in model_cls._fields else f for f in ut)
        for ut in getattr(model_cls, "_meta_unique_together", [])
    ]
    unique_together.sort()
    return unique_together


def build_model_index_together(model_cls: type[Model]) -> list[list[str]]:
    """Build the sorted index_together lists from Meta.index_together."""
    index_together = [
        sorted(model_cls._fields[f].column_name if f in model_cls._fields else f for f in it)
        for it in getattr(model_cls, "_meta_index_together", [])
    ]
    index_together.sort()
    return index_together
